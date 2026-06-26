package com.droidmarket;

import java.io.File;
import java.util.ArrayList;

import android.app.ListActivity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.TextView;
import android.widget.Toast;

public class DownloadsActivity extends ListActivity {

    private ArrayList<DownloadEntry> history;
    private DownloadHistoryAdapter adapter;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        ThemeManager.apply(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.downloads);

        findViewById(R.id.clear_all_btn).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                clearHistory();
            }
        });

        adapter = new DownloadHistoryAdapter(this);
        setListAdapter(adapter);

        loadHistory();
    }

    private void loadHistory() {
        history = getHistory(this);
        adapter.setData(history);
    }

    public static ArrayList<DownloadEntry> getHistory(Context context) {
        SharedPreferences prefs = context.getSharedPreferences("downloads", Context.MODE_PRIVATE);
        String raw = prefs.getString("history", "");
        ArrayList<DownloadEntry> list = new ArrayList<DownloadEntry>();
        if (raw.length() > 0) {
            String[] items = raw.split("\\|");
            for (String item : items) {
                String[] parts = item.split("\\~", 5);
                if (parts.length == 5) {
                    DownloadEntry e = new DownloadEntry();
                    e.packageName = parts[0];
                    e.appName = parts[1];
                    e.version = parts[2];
                    e.timestamp = parts[3];
                    e.filePath = parts[4];
                    if (new File(e.filePath).exists()) {
                        list.add(e);
                    }
                }
            }
        }
        return list;
    }

    public static void addToHistory(Context context, String pkg, String name, String version, String filePath) {
        SharedPreferences prefs = context.getSharedPreferences("downloads", Context.MODE_PRIVATE);
        String raw = prefs.getString("history", "");
        String entry = pkg + "~" + name + "~" + version + "~" + System.currentTimeMillis() + "~" + filePath;
        if (raw.length() == 0) {
            raw = entry;
        } else {
            raw = entry + "|" + raw;
        }
        prefs.edit().putString("history", raw).commit();
    }

    private void clearHistory() {
        getSharedPreferences("downloads", MODE_PRIVATE).edit().remove("history").commit();
        loadHistory();
        Toast.makeText(this, "History cleared", Toast.LENGTH_SHORT).show();
    }

    private void installApk(String path) {
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(Uri.fromFile(new File(path)),
                    "application/vnd.android.package-archive");
            startActivity(intent);
        } catch (Exception e) {
            Toast.makeText(this, "Can't open installer: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    public static class DownloadEntry {
        public String packageName;
        public String appName;
        public String version;
        public String timestamp;
        public String filePath;
    }

    private class DownloadHistoryAdapter extends BaseAdapter {
        private Context context;
        private ArrayList<DownloadEntry> items;
        private LayoutInflater inflater;

        public DownloadHistoryAdapter(Context context) {
            this.context = context;
            this.items = new ArrayList<DownloadEntry>();
            this.inflater = LayoutInflater.from(context);
        }

        public void setData(ArrayList<DownloadEntry> data) {
            this.items = data != null ? data : new ArrayList<DownloadEntry>();
            notifyDataSetChanged();
        }

        public int getCount() { return items.size(); }
        public DownloadEntry getItem(int i) { return items.get(i); }
        public long getItemId(int i) { return i; }

        public View getView(int position, View convertView, ViewGroup parent) {
            ViewHolder holder;
            if (convertView == null) {
                convertView = inflater.inflate(android.R.layout.simple_list_item_2, parent, false);
                holder = new ViewHolder();
                holder.text1 = (TextView) convertView.findViewById(android.R.id.text1);
                holder.text2 = (TextView) convertView.findViewById(android.R.id.text2);
                convertView.setTag(holder);
            } else {
                holder = (ViewHolder) convertView.getTag();
            }

            final DownloadEntry e = items.get(position);
            holder.text1.setText(e.appName + " v" + e.version);
            holder.text2.setText(e.filePath.substring(e.filePath.lastIndexOf('/') + 1));

            convertView.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) {
                    installApk(e.filePath);
                }
            });

            return convertView;
        }

        private class ViewHolder {
            TextView text1;
            TextView text2;
        }
    }
}
