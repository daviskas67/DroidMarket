package com.droidmarket;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;

import android.app.AlertDialog;
import android.app.ListActivity;
import android.app.ProgressDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.os.AsyncTask;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
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
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends ListActivity {

    private AppListAdapter adapter;
    private ArrayList<AppInfo> allApps;
    private EditText searchInput;
    private Button retryButton;
    private TextView countText;
    private ImageLoader imageLoader;
    private int sortMode; // 0=name, 1=downloads
    private LoadAppsTask loadAppsTask;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        ThemeManager.apply(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.main);

        ApiClient.setBaseUrl(ServerManager.getActiveUrl(this));

        searchInput = (EditText) findViewById(R.id.search_input);
        retryButton = (Button) findViewById(R.id.retry_button);
        countText = (TextView) findViewById(R.id.count_text);
        imageLoader = new ImageLoader();
        sortMode = 0;

        adapter = new AppListAdapter(this);
        setListAdapter(adapter);

        searchInput.addTextChangedListener(new TextWatcher() {
            public void afterTextChanged(Editable s) {
                filterApps(s.toString());
            }
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int count) {}
        });

        retryButton.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                loadApps();
            }
        });

        loadApps();
    }

    @Override
    protected void onDestroy() {
        if (loadAppsTask != null) {
            loadAppsTask.cancel(true);
            loadAppsTask = null;
        }
        super.onDestroy();
    }

    @Override
    protected void onListItemClick(ListView l, View v, int position, long id) {
        AppInfo app = adapter.getItem(position);
        if (app != null) {
            Intent intent = new Intent(MainActivity.this,
                    AppDetailActivity.class);
            intent.putExtra("app_id", app.id);
            intent.putExtra("app_name", app.name);
            intent.putExtra("app_icon", app.icon);
            intent.putExtra("app_package", app.packageName);
            intent.putExtra("app_downloads", app.downloads);
            intent.putExtra("app_versions", app.versionsCount);
            startActivity(intent);
        }
    }

    private void loadApps() {
        retryButton.setVisibility(View.GONE);
        loadAppsTask = new LoadAppsTask();
        loadAppsTask.execute();
    }

    private void filterApps(String query) {
        if (allApps == null) return;

        String q = query.toLowerCase().trim();
        ArrayList<AppInfo> filtered = new ArrayList<AppInfo>();

        if (q.length() == 0) {
            filtered.addAll(allApps);
        } else {
            for (AppInfo app : allApps) {
                if (app.name.toLowerCase().contains(q)
                        || app.packageName.toLowerCase().contains(q)) {
                    filtered.add(app);
                }
            }
        }

        adapter.setData(filtered);
        countText.setText(String.valueOf(filtered.size()));
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "Sort by Name").setIcon(android.R.drawable.ic_menu_sort_alphabetically);
        menu.add(0, 2, 0, "Sort by Downloads").setIcon(android.R.drawable.ic_menu_sort_by_size);
        menu.add(0, 3, 0, "About").setIcon(android.R.drawable.ic_menu_info_details);
        menu.add(0, 4, 0, "Theme: " + (ThemeManager.isMaterial(this) ? "Material" : "Holo"))
                .setIcon(android.R.drawable.ic_menu_gallery);
        menu.add(0, 5, 0, "Server: " + ServerManager.getActiveName(this))
                .setIcon(android.R.drawable.ic_menu_manage);
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        switch (item.getItemId()) {
            case 1: sortMode = 0; sortApps(); return true;
            case 2: sortMode = 1; sortApps(); return true;
            case 3:
                startActivity(new Intent(MainActivity.this, AboutActivity.class));
                return true;
            case 4:
                String newTheme = ThemeManager.isMaterial(this)
                        ? ThemeManager.THEME_HOLO : ThemeManager.THEME_MATERIAL;
                ThemeManager.set(this, newTheme);
                Toast.makeText(this, "Theme: " + (ThemeManager.isMaterial(this) ? "Material" : "Holo")
                        + " (restart required)", Toast.LENGTH_SHORT).show();
                return true;
            case 5:
                showServerDialog();
                return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void showServerDialog() {
        final ArrayList<ServerConfig> servers = ServerManager.getServers(this);
        final String[] names = new String[servers.size()];
        final String[] urls = new String[servers.size()];
        String active = ServerManager.getActiveUrl(this);
        int checked = 0;
        for (int i = 0; i < servers.size(); i++) {
            names[i] = servers.get(i).name;
            urls[i] = servers.get(i).url;
            if (urls[i].equals(active)) checked = i;
        }

        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle("Select Server");
        b.setSingleChoiceItems(names, checked, new DialogInterface.OnClickListener() {
            public void onClick(DialogInterface d, int which) {
                d.dismiss();
                ServerManager.setActiveUrl(MainActivity.this, urls[which]);
                Toast.makeText(MainActivity.this, "Server: " + names[which], Toast.LENGTH_SHORT).show();
                loadApps();
            }
        });
        b.setNeutralButton("Add Server", new DialogInterface.OnClickListener() {
            public void onClick(DialogInterface d, int which) {
                showAddServerDialog();
            }
        });
        b.setNegativeButton("Cancel", null);
        b.show();
    }

    private void showAddServerDialog() {
        final android.widget.EditText input = new android.widget.EditText(this);
        input.setHint("http://example.com");
        new AlertDialog.Builder(this)
                .setTitle("Add Server")
                .setMessage("Enter server URL:")
                .setView(input)
                .setPositiveButton("Add", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int which) {
                        String url = input.getText().toString().trim();
                        if (url.length() > 0) {
                            ArrayList<ServerConfig> servers = ServerManager.getServers(MainActivity.this);
                            String name = "Server " + (servers.size() + 1);
                            servers.add(new ServerConfig(name, url));
                            ServerManager.saveServers(MainActivity.this, servers);
                            Toast.makeText(MainActivity.this, "Added: " + name, Toast.LENGTH_SHORT).show();
                        }
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void sortApps() {
        if (allApps == null) return;
        if (sortMode == 1) {
            Collections.sort(allApps, new Comparator<AppInfo>() {
                public int compare(AppInfo a, AppInfo b) {
                    if (a.downloads > b.downloads) return -1;
                    if (a.downloads < b.downloads) return 1;
                    return 0;
                }
            });
        } else {
            Collections.sort(allApps, new Comparator<AppInfo>() {
                public int compare(AppInfo a, AppInfo b) {
                    return a.name.compareToIgnoreCase(b.name);
                }
            });
        }
        filterApps(searchInput.getText().toString());
    }

    private class LoadAppsTask extends AsyncTask<Void, String, ArrayList<AppInfo>> {
        private ProgressDialog dialog;
        private String error;

        @Override
        protected void onPreExecute() {
            dialog = ProgressDialog.show(MainActivity.this, "",
                    getString(R.string.loading), true, false);
        }

        @Override
        protected ArrayList<AppInfo> doInBackground(Void... params) {
            int maxRetries = 3;
            for (int attempt = 0; attempt < maxRetries; attempt++) {
                if (attempt > 0) {
                    publishProgress("Retrying (" + attempt + "/" + (maxRetries - 1) + ")...");
                    try { Thread.sleep(2000); } catch (InterruptedException e) { break; }
                }
                try {
                    return ApiClient.getApps(null);
                } catch (Exception e) {
                    error = e.getMessage();
                    if (attempt < maxRetries - 1) {
                        String msg = error != null ? error : "Connection failed";
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
        protected void onProgressUpdate(String... values) {
            if (dialog != null && dialog.isShowing()) {
                dialog.setMessage(values[0]);
            }
        }

        @Override
        protected void onPostExecute(ArrayList<AppInfo> result) {
            if (dialog != null && dialog.isShowing()) {
                dialog.dismiss();
            }

            if (result != null) {
                allApps = result;
                adapter.setData(result);
                countText.setText(String.valueOf(result.size()));
                retryButton.setVisibility(View.GONE);

                if (result.size() == 0) {
                    showError("No apps on server");
                }
            } else {
                showError(error != null ? error : "Connection failed");
                retryButton.setVisibility(View.VISIBLE);
            }
        }
    }

    private void showError(String msg) {
        new AlertDialog.Builder(this)
                .setTitle("Error")
                .setMessage(msg)
                .setPositiveButton("OK", null)
                .show();
    }

    private static class AppListAdapter extends BaseAdapter {
        private Context context;
        private ArrayList<AppInfo> apps;
        private LayoutInflater inflater;
        private ImageLoader imageLoader;

        public AppListAdapter(Context context) {
            this.context = context;
            this.apps = new ArrayList<AppInfo>();
            this.inflater = LayoutInflater.from(context);
            if (context instanceof MainActivity) {
                this.imageLoader = ((MainActivity) context).imageLoader;
            } else {
                this.imageLoader = new ImageLoader();
            }
        }

        public void setData(ArrayList<AppInfo> data) {
            this.apps = data != null ? data : new ArrayList<AppInfo>();
            notifyDataSetChanged();
        }

        public int getCount() {
            return apps.size();
        }

        public AppInfo getItem(int position) {
            return apps.get(position);
        }

        public long getItemId(int position) {
            return position;
        }

        public View getView(int position, View convertView, ViewGroup parent) {
            ViewHolder holder;

            if (convertView == null) {
                convertView = inflater.inflate(R.layout.app_item, parent, false);
                holder = new ViewHolder();
                holder.icon = (ImageView) convertView.findViewById(R.id.app_icon);
                holder.name = (TextView) convertView.findViewById(R.id.app_name);
                holder.pkg = (TextView) convertView.findViewById(R.id.app_package);
                holder.version = (TextView) convertView.findViewById(R.id.app_version);
                holder.size = (TextView) convertView.findViewById(R.id.app_size);
                holder.android = (TextView) convertView.findViewById(R.id.app_android);
                convertView.setTag(holder);
            } else {
                holder = (ViewHolder) convertView.getTag();
            }

            AppInfo app = apps.get(position);
            holder.name.setText(app.name);
            holder.pkg.setText(app.packageName);
            holder.version.setText("v" + app.version);
            holder.size.setText(app.sizeFormatted);
            holder.android.setText("Android " + app.androidVer + "+");

            if (app.icon != null && app.icon.length() > 0) {
                String iconUrl = ApiClient.getIconUrl(app.icon);
                imageLoader.load(iconUrl, holder.icon);
            } else {
                holder.icon.setImageResource(android.R.drawable.sym_def_app_icon);
            }

            return convertView;
        }

        private static class ViewHolder {
            ImageView icon;
            TextView name;
            TextView pkg;
            TextView version;
            TextView size;
            TextView android;
        }
    }
}
