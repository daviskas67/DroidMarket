package com.droidmarket;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.URLEncoder;
import java.util.ArrayList;
import org.apache.http.HttpEntity;
import org.apache.http.HttpResponse;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.conn.params.ConnManagerParams;
import org.apache.http.conn.params.ConnPerRouteBean;
import org.apache.http.impl.client.DefaultHttpClient;
import org.apache.http.params.HttpConnectionParams;
import org.apache.http.params.HttpParams;
import org.json.JSONArray;
import org.json.JSONObject;

public class ApiClient {

    private static String BASE_URL = "http://barbaros.serveousercontent.com";
    private static DefaultHttpClient sharedClient;

    public static void setBaseUrl(String url) {
        if (url != null && url.length() > 0) {
            BASE_URL = url;
        }
    }

    public static String getBaseUrl() {
        return BASE_URL;
    }

    public static DefaultHttpClient getSharedClient() {
        if (sharedClient == null) {
            sharedClient = new DefaultHttpClient();
            HttpParams params = sharedClient.getParams();
            HttpConnectionParams.setConnectionTimeout(params, 30000);
            HttpConnectionParams.setSoTimeout(params, 120000);
            ConnManagerParams.setMaxTotalConnections(params, 20);
            ConnManagerParams.setMaxConnectionsPerRoute(params, new ConnPerRouteBean(10));
        }
        return sharedClient;
    }

    private static String readStream(InputStream is) throws Exception {
        try {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) != -1) {
                bos.write(buf, 0, n);
            }
            return new String(bos.toByteArray(), "UTF-8");
        } finally {
            try { is.close(); } catch (Exception ignored) {}
        }
    }

    private static String httpGet(String url) throws Exception {
        DefaultHttpClient client = getSharedClient();
        HttpGet request = new HttpGet(url);
        request.setHeader("User-Agent", "DroidMarket/1.0 (Android 1.6)");
        HttpResponse response = client.execute(request);

        int status = response.getStatusLine().getStatusCode();
        if (status != 200) {
            throw new Exception("HTTP " + status);
        }

        HttpEntity entity = null;
        try {
            entity = response.getEntity();
            if (entity == null) {
                throw new Exception("Empty response");
            }
            return readStream(entity.getContent());
        } finally {
            if (entity != null) {
                try { entity.consumeContent(); } catch (Exception ignored) {}
            }
        }
    }

    public static ArrayList<AppInfo> getApps(String query) throws Exception {
        String url = BASE_URL + "/api/apps";
        if (query != null && query.length() > 0) {
            url += "?q=" + URLEncoder.encode(query, "UTF-8");
        }

        String json = httpGet(url);
        JSONArray arr = new JSONArray(json);

        ArrayList<AppInfo> apps = new ArrayList<AppInfo>();
        for (int i = 0; i < arr.length(); i++) {
            JSONObject obj = arr.getJSONObject(i);
            AppInfo app = new AppInfo();
            app.id = obj.optInt("id", 0);
            app.packageName = obj.optString("package", "");
            app.name = obj.optString("name", "");
            app.icon = obj.optString("icon", "");
            app.version = obj.optString("version", "?");
            app.androidVer = androidVersion(obj.optString("android_ver", "?"));
            app.minSdk = obj.optString("min_sdk", "?");
            app.size = obj.optLong("size", 0);
            app.sizeFormatted = obj.optString("size_formatted", "0 B");
            app.type = obj.optString("type", "apk");
            app.downloads = obj.optInt("downloads", 0);
            app.versionsCount = obj.optInt("versions_count", 0);
            app.addedDate = obj.optString("added_date", "");
            apps.add(app);
        }
        return apps;
    }

    public static ArrayList<AppVersion> getVersions(int appId) throws Exception {
        String url = BASE_URL + "/api/app/" + appId + "/versions";
        String json = httpGet(url);
        JSONArray arr = new JSONArray(json);

        ArrayList<AppVersion> versions = new ArrayList<AppVersion>();
        for (int i = 0; i < arr.length(); i++) {
            JSONObject obj = arr.getJSONObject(i);
            AppVersion v = new AppVersion();
            v.version = obj.optString("version", "?");
            v.filename = obj.optString("filename", "");
            v.size = obj.optLong("size", 0);
            v.minSdk = obj.optString("min_sdk", "?");
            v.downloads = obj.optInt("downloads", 0);
            v.sizeFormatted = formatSize(v.size);
            v.androidVer = androidVersion(v.minSdk);
            versions.add(v);
        }
        return versions;
    }

    public static String getDownloadUrl(int appId, String version) {
        try {
            return BASE_URL + "/api/download/" + appId + "/"
                    + URLEncoder.encode(version, "UTF-8");
        } catch (Exception e) {
            return BASE_URL + "/api/download/" + appId + "/" + version;
        }
    }

    public static String getIconUrl(String iconName) {
        try {
            return BASE_URL + "/html/apps/" + URLEncoder.encode(iconName, "UTF-8");
        } catch (Exception e) {
            return BASE_URL + "/html/apps/" + iconName;
        }
    }

    public interface DownloadProgress {
        void onProgress(long downloaded, long total);
    }

    public static String downloadFile(int appId, String version,
            File destination) throws Exception {
        return downloadFile(appId, version, destination, null);
    }

    public static String downloadFile(int appId, String version,
            File destination, DownloadProgress progress) throws Exception {
        String url = getDownloadUrl(appId, version);

        DefaultHttpClient client = getSharedClient();
        HttpGet request = new HttpGet(url);
        request.setHeader("User-Agent", "DroidMarket/1.0 (Android 1.6)");
        HttpResponse response = client.execute(request);

        int status = response.getStatusLine().getStatusCode();
        if (status != 200) {
            throw new Exception("Download failed: HTTP " + status);
        }

        HttpEntity entity = null;
        try {
            entity = response.getEntity();
            if (entity == null) {
                throw new Exception("No data");
            }

            long total = entity.getContentLength();
            InputStream is = entity.getContent();
            FileOutputStream fos = new FileOutputStream(destination);
            try {
                byte[] buf = new byte[8192];
                int n;
                long downloaded = 0;
                long nextProgress = 0;
                while ((n = is.read(buf)) != -1) {
                    fos.write(buf, 0, n);
                    downloaded += n;
                    if (progress != null && total > 0 && downloaded >= nextProgress) {
                        progress.onProgress(downloaded, total);
                        nextProgress = downloaded + 65536;
                    }
                }
            } finally {
                try { fos.close(); } catch (Exception ignored) {}
                try { is.close(); } catch (Exception ignored) {}
            }
        } finally {
            if (entity != null) {
                try { entity.consumeContent(); } catch (Exception ignored) {}
            }
        }

        return destination.getAbsolutePath();
    }

    private static String formatSize(long bytes) {
        String[] units = {"B", "KB", "MB", "GB"};
        double b = bytes;
        int u = 0;
        while (b >= 1024 && u < units.length - 1) {
            b /= 1024.0;
            u++;
        }
        return String.format("%.1f %s", b, units[u]);
    }

    private static String androidVersion(String minSdk) {
        try {
            int sdk = Integer.parseInt(minSdk);
            switch (sdk) {
                case 1: return "1.0";
                case 2: return "1.1";
                case 3: return "1.5 Cupcake";
                case 4: return "1.6 Donut";
                case 5: return "2.0 Eclair";
                case 6: return "2.0.1 Eclair";
                case 7: return "2.1 Eclair";
                case 8: return "2.2 Froyo";
                case 9: return "2.3 Gingerbread";
                case 10: return "2.3.3 Gingerbread";
                case 11: return "3.0 Honeycomb";
                case 12: return "3.1 Honeycomb";
                case 13: return "3.2 Honeycomb";
                case 14: return "4.0 Ice Cream Sandwich";
                case 15: return "4.0.3 Ice Cream Sandwich";
                case 16: return "4.1 Jelly Bean";
                case 17: return "4.2 Jelly Bean";
                case 18: return "4.3 Jelly Bean";
                case 19: return "4.4 KitKat";
                case 21: return "5.0 Lollipop";
                case 22: return "5.1 Lollipop";
                case 23: return "6.0 Marshmallow";
                case 24: return "7.0 Nougat";
                case 25: return "7.1 Nougat";
                case 26: return "8.0 Oreo";
                case 27: return "8.1 Oreo";
                case 28: return "9.0 Pie";
                case 29: return "10.0";
                case 30: return "11.0";
                case 31: return "12.0";
                case 33: return "13.0";
                case 34: return "14.0";
                default: return "API " + sdk;
            }
        } catch (Exception e) {
            return minSdk;
        }
    }
}
