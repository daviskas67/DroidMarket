package com.droidmarket;

import java.io.File;
import java.util.ArrayList;

import java.io.File;
import java.util.HashSet;
import java.util.Set;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.ProgressDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.Environment;
import android.view.LayoutInflater;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.ListView;
import android.widget.RatingBar;
import android.widget.TextView;
import android.widget.Toast;

public class AppDetailActivity extends Activity {

    private int appId;
    private String appName;
    private String appIcon;
    private String appPackage;
    private String appAddedDate;
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
            appAddedDate = intent.getStringExtra("app_added_date");

            int downloads = intent.getIntExtra("app_downloads", 0);
            int versions = intent.getIntExtra("app_versions", 0);

            addRecentlyViewed();

            imageLoader = new ImageLoader();

            setTitle(appName != null ? appName : "App");

            ImageView iconView = (ImageView) findViewById(R.id.detail_icon);
            iconView.setImageResource(android.R.drawable.sym_def_app_icon);

            TextView nameView = (TextView) findViewById(R.id.detail_name);
            nameView.setText(String.valueOf(appName));

            TextView pkgView = (TextView) findViewById(R.id.detail_package);
            pkgView.setText(String.valueOf(appPackage));

            TextView dateView = (TextView) findViewById(R.id.detail_date);
            if (appAddedDate != null && appAddedDate.length() > 0) {
                String d = appAddedDate;
                if (d.length() > 10) d = d.substring(0, 10);
                dateView.setText("Added: " + d);
                dateView.setVisibility(View.VISIBLE);
            } else {
                dateView.setVisibility(View.GONE);
            }

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

    private boolean isFavorite() {
        SharedPreferences prefs = getSharedPreferences("favorites", MODE_PRIVATE);
        String raw = prefs.getString("list", "");
        if (raw.length() > 0) {
            String[] parts = raw.split("\\|");
            for (String p : parts) {
                if (p.equals(appPackage)) return true;
            }
        }
        return false;
    }

    private void toggleFavorite() {
        SharedPreferences prefs = getSharedPreferences("favorites", MODE_PRIVATE);
        String raw = prefs.getString("list", "");
        Set<String> set = new HashSet<String>();
        if (raw.length() > 0) {
            String[] parts = raw.split("\\|");
            for (String p : parts) {
                if (p.length() > 0) set.add(p);
            }
        }
        if (set.contains(appPackage)) {
            set.remove(appPackage);
            Toast.makeText(this, "Removed from Favorites", Toast.LENGTH_SHORT).show();
        } else {
            set.add(appPackage);
            Toast.makeText(this, "Added to Favorites", Toast.LENGTH_SHORT).show();
        }
        StringBuilder sb = new StringBuilder();
        for (String p : set) {
            if (sb.length() > 0) sb.append("|");
            sb.append(p);
        }
        prefs.edit().putString("list", sb.toString()).commit();
    }

    private void addRecentlyViewed() {
        SharedPreferences prefs = getSharedPreferences("lists", MODE_PRIVATE);
        String raw = prefs.getString("recently_viewed", "");
        StringBuilder sb = new StringBuilder(appPackage);
        if (raw.length() > 0) {
            String[] parts = raw.split("\\|");
            int count = 0;
            for (String p : parts) {
                if (!p.equals(appPackage) && count < 19) {
                    sb.append("|").append(p);
                    count++;
                }
            }
        }
        prefs.edit().putString("recently_viewed", sb.toString()).commit();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, isFavorite() ? "Unfavorite" : "Favorite").setIcon(android.R.drawable.ic_menu_myplaces);
        menu.add(0, 2, 0, "Share Link").setIcon(R.drawable.ic_menu_market_share);
        menu.add(0, 3, 0, "Open in Browser").setIcon(android.R.drawable.ic_menu_compass);
        menu.add(0, 4, 0, "App Notes").setIcon(0);
        menu.add(0, 5, 0, "Rate App").setIcon(0);
        menu.add(0, 6, 0, "Share APK").setIcon(0);
        return true;
    }

    @Override
    public boolean onPrepareOptionsMenu(Menu menu) {
        try {
            menu.getItem(0).setTitle(isFavorite() ? "Unfavorite" : "Favorite");
        } catch (Exception ignored) {}
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        switch (item.getItemId()) {
            case 1: toggleFavorite(); return true;
            case 2: shareApp(); return true;
            case 3: openInBrowser(); return true;
            case 4: showNotesDialog(); return true;
            case 5: showRatingDialog(); return true;
            case 6: shareApkFile(); return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void openInBrowser() {
        try {
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setData(Uri.parse(ApiClient.getBaseUrl() + "/app/" + appPackage));
            startActivity(i);
        } catch (Exception e) {
            Toast.makeText(this, "Cannot open browser", Toast.LENGTH_SHORT).show();
        }
    }

    private void showNotesDialog() {
        SharedPreferences prefs = getSharedPreferences("notes", MODE_PRIVATE);
        final String saved = prefs.getString(appPackage, "");

        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle("Notes for " + appName);
        final EditText input = new EditText(this);
        input.setText(saved);
        input.setHint("Write a note...");
        b.setView(input);
        b.setPositiveButton("Save", new DialogInterface.OnClickListener() {
            public void onClick(DialogInterface d, int w) {
                String note = input.getText().toString().trim();
                getSharedPreferences("notes", MODE_PRIVATE).edit().putString(appPackage, note).commit();
                Toast.makeText(AppDetailActivity.this, note.length() > 0 ? "Note saved" : "Note removed", Toast.LENGTH_SHORT).show();
            }
        });
        b.setNegativeButton("Cancel", null);
        b.show();
    }

    private void showRatingDialog() {
        SharedPreferences prefs = getSharedPreferences("ratings", MODE_PRIVATE);
        final int current = prefs.getInt(appPackage, 0);

        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle("Rate " + appName);
        final RatingBar ratingBar = new RatingBar(this);
        ratingBar.setNumStars(5);
        ratingBar.setStepSize(1.0f);
        if (current > 0) ratingBar.setRating(current);
        ratingBar.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        b.setView(ratingBar);
        b.setPositiveButton("Save", new DialogInterface.OnClickListener() {
            public void onClick(DialogInterface d, int w) {
                int rating = (int) ratingBar.getRating();
                getSharedPreferences("ratings", MODE_PRIVATE).edit().putInt(appPackage, rating).commit();
                Toast.makeText(AppDetailActivity.this,
                        rating > 0 ? "Rated: " + rating + "/5" : "Rating removed",
                        Toast.LENGTH_SHORT).show();
            }
        });
        b.setNegativeButton("Cancel", null);
        b.show();
    }

    private void shareApkFile() {
        File dir = new File(Environment.getExternalStorageDirectory(), "Download");
        final String prefix = (appPackage != null ? appPackage : "app") + "_";
        File[] files = dir.listFiles();
        if (files != null) {
            for (File f : files) {
                if (f.getName().startsWith(prefix) && f.getName().endsWith(".apk")) {
                    try {
                        Intent share = new Intent(Intent.ACTION_SEND);
                        share.setType("application/vnd.android.package-archive");
                        share.putExtra(Intent.EXTRA_STREAM, Uri.fromFile(f));
                        startActivity(Intent.createChooser(share, "Share APK"));
                        return;
                    } catch (Exception e) {
                        Toast.makeText(this, "Share failed", Toast.LENGTH_SHORT).show();
                        return;
                    }
                }
            }
        }
        Toast.makeText(this, "No APK file found. Download it first.", Toast.LENGTH_SHORT).show();
    }

    private void shareApp() {
        try {
            Intent share = new Intent(Intent.ACTION_SEND);
            share.setType("text/plain");
            String text = appName + " (" + appPackage + ") — DroidMarket\n" +
                    ApiClient.getBaseUrl() + "/app/" + appPackage;
            share.putExtra(Intent.EXTRA_TEXT, text);
            startActivity(Intent.createChooser(share, "Share App"));
        } catch (Exception e) {
            Toast.makeText(this, "Share failed: " + e.getMessage(), Toast.LENGTH_SHORT).show();
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
        if (loadTask != null) {
            loadTask.cancel(true);
            loadTask = null;
        }
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

            if (isFinishing()) return;

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
        private View.OnClickListener clickListener;

        public VersionListAdapter(Context context) {
            this.context = context;
            this.versions = new ArrayList<AppVersion>();
            this.inflater = LayoutInflater.from(context);
            this.clickListener = new View.OnClickListener() {
                public void onClick(View v) {
                    Object tag = v.getTag();
                    if (tag instanceof Integer) {
                        int pos = ((Integer) tag).intValue();
                        if (pos >= 0 && pos < versions.size()) {
                            startDownload(versions.get(pos));
                        }
                    }
                }
            };
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
                    holder.downloadBtn.setOnClickListener(clickListener);
                    convertView.setTag(holder);
                } else {
                    holder = (ViewHolder) convertView.getTag();
                }

                if (position >= versions.size()) return convertView;
                AppVersion ver = versions.get(position);
                holder.version.setText("v" + ver.version);
                holder.size.setText(ver.sizeFormatted);
                holder.android.setText("Android " + ver.androidVer + "+");
                holder.downloadBtn.setTag(Integer.valueOf(position));

                return convertView;
            } catch (Exception e) {
                if (convertView == null) {
                    convertView = new View(parent.getContext());
                    convertView.setLayoutParams(new ViewGroup.LayoutParams(
                            ViewGroup.LayoutParams.FILL_PARENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT));
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
        if (downloadTask != null) {
            downloadTask.cancel(true);
            downloadTask = null;
        }
        downloadTask = new DownloadTask();
        downloadTask.execute(ver);
    }

    private class DownloadTask extends AsyncTask<AppVersion, Integer, String> {
        private ProgressDialog dialog;
        private String error;
        private long totalBytes;
        private AppVersion currentVer;

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
            currentVer = params[0];
            AppVersion ver = currentVer;
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

            if (isFinishing()) return;

            if (path != null) {
                DownloadsActivity.addToHistory(AppDetailActivity.this,
                        appPackage, appName, currentVer.version, path);
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
