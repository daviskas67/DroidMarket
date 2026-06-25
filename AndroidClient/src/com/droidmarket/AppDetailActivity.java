package com.droidmarket;

import java.io.File;
import java.util.ArrayList;

import android.app.Activity;
import android.app.ProgressDialog;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.Environment;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

public class AppDetailActivity extends Activity {

    private int appId;
    private String appName;
    private String appIcon;
    private String appPackage;
    private ImageLoader imageLoader;

    private TextView versionsHeader;
    private ListView versionList;
    private VersionListAdapter adapter;

    private LoadVersionsTask loadTask;
    private DownloadTask downloadTask;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        ThemeManager.apply(this);
        super.onCreate(savedInstanceState);
        try {
            setContentView(R.layout.detail);

            Intent intent = getIntent();
            appId = intent.getIntExtra("app_id", 0);
            appName = intent.getStringExtra("app_name");
            appIcon = intent.getStringExtra("app_icon");
            appPackage = intent.getStringExtra("app_package");

            int downloads = intent.getIntExtra("app_downloads", 0);
            int versions = intent.getIntExtra("app_versions", 0);

            imageLoader = new ImageLoader();

            setTitle(appName != null ? appName : "App");

            ImageView iconView = (ImageView) findViewById(R.id.detail_icon);
            iconView.setImageResource(android.R.drawable.sym_def_app_icon);

            TextView nameView = (TextView) findViewById(R.id.detail_name);
            nameView.setText(String.valueOf(appName));

            TextView pkgView = (TextView) findViewById(R.id.detail_package);
            pkgView.setText(String.valueOf(appPackage));

            TextView versionsCountView = (TextView) findViewById(R.id.detail_versions_count);
            versionsCountView.setText(String.valueOf(versions));

            TextView downloadsView = (TextView) findViewById(R.id.detail_downloads);
            downloadsView.setText(String.valueOf(downloads));

            versionsHeader = (TextView) findViewById(R.id.versions_header);

            versionList = (ListView) findViewById(R.id.version_list);
            adapter = new VersionListAdapter(this);
            versionList.setAdapter(adapter);

            loadVersions();

            if (appIcon != null && appIcon.length() > 0) {
                imageLoader.load(ApiClient.getIconUrl(appIcon), iconView);
            }
        } catch (Exception e) {
            Toast.makeText(this, "Error: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onDestroy() {
        if (loadTask != null) {
            loadTask.cancel(true);
            loadTask = null;
        }
        if (downloadTask != null) {
            downloadTask.cancel(true);
            downloadTask = null;
        }
        super.onDestroy();
    }

    private void loadVersions() {
        versionsHeader.setText("Loading versions...");
        loadTask = new LoadVersionsTask();
        loadTask.execute(appId);
    }

    private class LoadVersionsTask extends
            AsyncTask<Integer, Void, ArrayList<AppVersion>> {
        private ProgressDialog dialog;
        private String error;

        @Override
        protected void onPreExecute() {
            try {
                dialog = ProgressDialog.show(AppDetailActivity.this, "",
                        "Loading versions...", true, false);
            } catch (Exception e) {
                dialog = null;
            }
        }

        @Override
        protected ArrayList<AppVersion> doInBackground(Integer... params) {
            int maxRetries = 3;
            for (int attempt = 0; attempt < maxRetries; attempt++) {
                if (isCancelled()) return null;
                if (attempt > 0) {
                    try { Thread.sleep(2000); } catch (InterruptedException e) { return null; }
                }
                try {
                    return ApiClient.getVersions(params[0]);
                } catch (Exception e) {
                    error = e.getMessage();
                    if (attempt < maxRetries - 1) {
                        String msg = error != null ? error : "";
                        if (!msg.contains("502") && !msg.contains("timeout")
                                && !msg.contains("refused") && !msg.contains("unreachable")) {
                            break;
                        }
                    }
                }
            }
            return null;
        }

        @Override
        protected void onPostExecute(ArrayList<AppVersion> result) {
            if (isCancelled()) return;
            if (dialog != null && dialog.isShowing()) {
                try { dialog.dismiss(); } catch (Exception ignored) {}
            }

            if (result != null) {
                adapter.setData(result);
                versionsHeader.setText("Versions (" + result.size() + ")");
            } else {
                versionsHeader.setText("Failed to load versions");
                String msg = error != null ? error : "Connection failed";
                Toast.makeText(AppDetailActivity.this,
                        "Error: " + msg, Toast.LENGTH_LONG).show();
            }
        }
    }

    private class VersionListAdapter extends BaseAdapter {
        private Context context;
        private ArrayList<AppVersion> versions;
        private LayoutInflater inflater;

        public VersionListAdapter(Context context) {
            this.context = context;
            this.versions = new ArrayList<AppVersion>();
            this.inflater = LayoutInflater.from(context);
        }

        public void setData(ArrayList<AppVersion> data) {
            this.versions = data != null ? data : new ArrayList<AppVersion>();
            notifyDataSetChanged();
        }

        public int getCount() {
            return versions.size();
        }

        public AppVersion getItem(int position) {
            return versions.get(position);
        }

        public long getItemId(int position) {
            return position;
        }

        public View getView(int position, View convertView, ViewGroup parent) {
            try {
                ViewHolder holder;

                if (convertView == null) {
                    convertView = inflater.inflate(R.layout.version_item, parent, false);
                    holder = new ViewHolder();
                    holder.version = (TextView) convertView
                            .findViewById(R.id.ver_version);
                    holder.size = (TextView) convertView
                            .findViewById(R.id.ver_size);
                    holder.android = (TextView) convertView
                            .findViewById(R.id.ver_android);
                    holder.downloadBtn = (Button) convertView
                            .findViewById(R.id.ver_download);
                    convertView.setTag(holder);
                } else {
                    holder = (ViewHolder) convertView.getTag();
                }

                final AppVersion ver = versions.get(position);
                holder.version.setText("v" + ver.version);
                holder.size.setText(ver.sizeFormatted);
                holder.android.setText("Android " + ver.androidVer + "+");

                holder.downloadBtn.setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) {
                        startDownload(ver);
                    }
                });

                return convertView;
            } catch (Exception e) {
                if (convertView == null) {
                    convertView = new View(parent.getContext());
                }
                return convertView;
            }
        }

        private class ViewHolder {
            TextView version;
            TextView size;
            TextView android;
            Button downloadBtn;
        }
    }

    private void startDownload(final AppVersion ver) {
        downloadTask = new DownloadTask();
        downloadTask.execute(ver);
    }

    private class DownloadTask extends AsyncTask<AppVersion, Integer, String> {
        private ProgressDialog dialog;
        private String error;
        private long totalBytes;

        @Override
        protected void onPreExecute() {
            dialog = new ProgressDialog(AppDetailActivity.this);
            dialog.setProgressStyle(ProgressDialog.STYLE_HORIZONTAL);
            dialog.setMessage("Downloading...");
            dialog.setCancelable(false);
            try {
                dialog.show();
            } catch (Exception e) {
                dialog = null;
            }
        }

        @Override
        protected String doInBackground(AppVersion... params) {
            AppVersion ver = params[0];
            int maxRetries = 3;
            for (int attempt = 0; attempt < maxRetries; attempt++) {
                if (isCancelled()) return null;
                if (attempt > 0) {
                    try { Thread.sleep(2000); } catch (InterruptedException e) { return null; }
                }
                try {
                    File sd = Environment.getExternalStorageDirectory();
                    if (sd == null) {
                        error = "No SD card found";
                        break;
                    }
                    File dir = new File(sd, "Download");
                    if (!dir.exists()) { dir.mkdirs(); }
                    String fileName = (appPackage != null ? appPackage : "app") + "_v" + ver.version + ".apk";
                    fileName = fileName.replaceAll("[^a-zA-Z0-9._-]", "_");
                    File dest = new File(dir, fileName);
                    return ApiClient.downloadFile(appId, ver.version, dest,
                            new ApiClient.DownloadProgress() {
                                public void onProgress(long downloaded, long total) {
                                    totalBytes = total;
                                    publishProgress((int) downloaded, (int) total);
                                }
                            });
                } catch (Exception e) {
                    error = e.getMessage();
                    if (attempt < maxRetries - 1) {
                        String msg = error != null ? error : "";
                        if (!msg.contains("502") && !msg.contains("timeout")
                                && !msg.contains("refused") && !msg.contains("unreachable")) {
                            break;
                        }
                    }
                }
            }
            return null;
        }

        @Override
        protected void onProgressUpdate(Integer... values) {
            if (dialog != null && dialog.isShowing()) {
                try {
                    dialog.setMax(values[1]);
                    dialog.setProgress(values[0]);
                } catch (Exception ignored) {}
            }
        }

        @Override
        protected void onPostExecute(String path) {
            if (isCancelled()) return;
            if (dialog != null && dialog.isShowing()) {
                try { dialog.dismiss(); } catch (Exception ignored) {}
            }

            if (path != null) {
                try {
                    Intent intent = new Intent(Intent.ACTION_VIEW);
                    intent.setDataAndType(Uri.fromFile(new File(path)),
                            "application/vnd.android.package-archive");
                    startActivity(intent);
                } catch (Exception e) {
                    Toast.makeText(AppDetailActivity.this,
                            "Can't open installer: " + e.getMessage(),
                            Toast.LENGTH_LONG).show();
                }
            } else {
                String msg = error != null ? error : "Download failed";
                if (msg != null && msg.contains("502")) {
                    msg = "Server error (502). Try again later.";
                }
                Toast.makeText(AppDetailActivity.this,
                        msg != null ? msg : "Download failed", Toast.LENGTH_LONG).show();
            }
        }
    }
}
