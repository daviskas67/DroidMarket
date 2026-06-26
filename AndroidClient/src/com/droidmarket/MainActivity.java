package com.droidmarket;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.view.KeyEvent;
import android.view.inputmethod.EditorInfo;

import android.app.AlertDialog;
import android.app.ListActivity;
import android.app.ProgressDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.Environment;
import android.text.ClipboardManager;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.LayoutInflater;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends ListActivity {

    private static final String PREFS_FAVORITES = "favorites";

    private AppListAdapter adapter;
    private ArrayList<AppInfo> allApps;
    private EditText searchInput;
    private Button retryButton;
    private TextView sectionHeader;
    private ImageLoader imageLoader;
    private int sortMode;
    private LoadAppsTask loadAppsTask;

    private int filterMode;
    private Set<String> favoritesSet;
    private ArrayList<AppInfo> updatableApps;
    private Map<String, String> installedVersions;
    private Handler autoRefreshHandler;
    private Runnable autoRefreshRunnable;
    private boolean autoRefreshEnabled;
    private ArrayList<String> searchHistory;
    private ArrayList<String> recentlyViewed;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        ThemeManager.apply(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.main);

        ApiClient.setBaseUrl(ServerManager.getActiveUrl(this));

        searchInput = (EditText) findViewById(R.id.search_input);
        retryButton = (Button) findViewById(R.id.retry_button);
        sectionHeader = (TextView) findViewById(R.id.section_header);
        imageLoader = new ImageLoader();
        sortMode = 0;
        filterMode = 0;
        favoritesSet = loadFavorites();
        updatableApps = null;
        installedVersions = null;
        searchHistory = loadStringList("search_history");
        recentlyViewed = loadStringList("recently_viewed");
        autoRefreshEnabled = getSharedPreferences("settings", MODE_PRIVATE).getBoolean("auto_refresh", false);
        autoRefreshHandler = new Handler();
        if (autoRefreshEnabled) startAutoRefresh();

        adapter = new AppListAdapter(this);
        setListAdapter(adapter);

        searchInput.addTextChangedListener(new TextWatcher() {
            public void afterTextChanged(Editable s) {
                filterApps(s.toString());
            }
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int count) {}
        });
        searchInput.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            public boolean onEditorAction(TextView v, int actionId, KeyEvent event) {
                if (event != null && event.getAction() == KeyEvent.ACTION_DOWN) {
                    addSearchQuery(v.getText().toString());
                }
                return false;
            }
        });
        updateSearchSuggestions();

        retryButton.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                loadApps();
            }
        });

        getListView().setOnItemLongClickListener(new AdapterView.OnItemLongClickListener() {
            public boolean onItemLongClick(AdapterView<?> parent, View view,
                    int position, long id) {
                AppInfo app = adapter.getItem(position);
                if (app != null && app.packageName != null
                        && app.packageName.length() > 0) {
                    showAppActionsDialog(app);
                    return true;
                }
                return false;
            }
        });

        loadApps();
    }

    @Override
    protected void onResume() {
        super.onResume();
        favoritesSet = loadFavorites();
        if (filterMode == 1) filterApps(searchInput.getText().toString());
    }

    @Override
    protected void onDestroy() {
        if (loadAppsTask != null) {
            loadAppsTask.cancel(true);
            loadAppsTask = null;
        }
        super.onDestroy();
    }

    private ArrayList<String> loadStringList(String key) {
        String raw = getSharedPreferences("lists", MODE_PRIVATE).getString(key, "");
        ArrayList<String> list = new ArrayList<String>();
        if (raw.length() > 0) {
            String[] parts = raw.split("\\|");
            for (String p : parts) { if (p.length() > 0) list.add(p); }
        }
        return list;
    }

    private void saveStringList(String key, ArrayList<String> list) {
        StringBuilder sb = new StringBuilder();
        for (String s : list) {
            if (sb.length() > 0) sb.append("|");
            sb.append(s);
        }
        getSharedPreferences("lists", MODE_PRIVATE).edit().putString(key, sb.toString()).commit();
    }

    private void addSearchQuery(String q) {
        q = q.trim();
        if (q.length() == 0) return;
        searchHistory.remove(q);
        searchHistory.add(0, q);
        if (searchHistory.size() > 10) searchHistory.remove(searchHistory.size() - 1);
        saveStringList("search_history", searchHistory);
        updateSearchSuggestions();
    }

    private void updateSearchSuggestions() {
        String input = searchInput.getText().toString().trim().toLowerCase();
        if (input.length() > 0 || filterMode != 0) return;
        if (searchHistory.isEmpty()) return;
        StringBuilder sb = new StringBuilder("Recent: ");
        int count = 0;
        for (String q : searchHistory) {
            if (count >= 3) break;
            if (count > 0) sb.append("  |  ");
            sb.append(q);
            count++;
        }
        searchInput.setHint(sb.toString());
    }

    private void startAutoRefresh() {
        autoRefreshRunnable = new Runnable() {
            public void run() {
                if (autoRefreshEnabled && allApps != null) {
                    loadApps();
                }
            }
        };
        autoRefreshHandler.postDelayed(autoRefreshRunnable, 60000);
    }

    private void stopAutoRefresh() {
        if (autoRefreshRunnable != null) {
            autoRefreshHandler.removeCallbacks(autoRefreshRunnable);
        }
    }

    private void clearAllData() {
        new AlertDialog.Builder(this)
                .setTitle("Clear All Data")
                .setMessage("Reset favorites, search history, recently viewed, and settings?")
                .setPositiveButton("Clear", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) {
                        getSharedPreferences("favorites", MODE_PRIVATE).edit().clear().commit();
                        getSharedPreferences("lists", MODE_PRIVATE).edit().clear().commit();
                        getSharedPreferences("settings", MODE_PRIVATE).edit().clear().commit();
                        getSharedPreferences("downloads", MODE_PRIVATE).edit().clear().commit();
                        searchHistory.clear();
                        recentlyViewed.clear();
                        favoritesSet.clear();
                        imageLoader.clearCache();
                        Toast.makeText(MainActivity.this, "All data cleared", Toast.LENGTH_SHORT).show();
                        loadApps();
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void exportFavorites() {
        if (favoritesSet.isEmpty()) {
            Toast.makeText(this, "No favorites to export", Toast.LENGTH_SHORT).show();
            return;
        }
        try {
            File dir = new File(Environment.getExternalStorageDirectory(), "DroidMarket");
            if (!dir.exists()) dir.mkdirs();
            File f = new File(dir, "favorites.txt");
            FileWriter fw = new FileWriter(f);
            for (String pkg : favoritesSet) {
                fw.write(pkg + "\n");
            }
            fw.close();
            Toast.makeText(this, "Favorites exported to " + f.getAbsolutePath(), Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "Export failed: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    private void importFavorites() {
        try {
            File dir = new File(Environment.getExternalStorageDirectory(), "DroidMarket");
            File f = new File(dir, "favorites.txt");
            if (!f.exists()) {
                Toast.makeText(this, "File not found: " + f.getAbsolutePath(), Toast.LENGTH_LONG).show();
                return;
            }
            BufferedReader br = new BufferedReader(new FileReader(f));
            String line;
            int count = 0;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.length() > 0 && favoritesSet.add(line)) count++;
            }
            br.close();
            saveFavorites(favoritesSet);
            Toast.makeText(this, "Imported " + count + " favorites", Toast.LENGTH_SHORT).show();
            if (filterMode == 1) filterApps(searchInput.getText().toString());
        } catch (Exception e) {
            Toast.makeText(this, "Import failed: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    private void showRecentlyViewed() {
        if (recentlyViewed.isEmpty()) {
            Toast.makeText(this, "No recently viewed apps", Toast.LENGTH_SHORT).show();
            return;
        }
        final String[] names = recentlyViewed.toArray(new String[0]);
        new AlertDialog.Builder(this)
                .setTitle("Recently Viewed")
                .setItems(names, new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) {
                        String pkg = recentlyViewed.get(w);
                        if (allApps != null) {
                            for (AppInfo app : allApps) {
                                if (app.packageName.equals(pkg)) {
                                    openAppDetail(app);
                                    return;
                                }
                            }
                        }
                        Toast.makeText(MainActivity.this, "App not in list", Toast.LENGTH_SHORT).show();
                    }
                })
                .show();
    }

    private void openAppDetail(AppInfo app) {
        Intent intent = new Intent(MainActivity.this, AppDetailActivity.class);
        intent.putExtra("app_id", app.id);
        intent.putExtra("app_name", app.name);
        intent.putExtra("app_icon", app.icon);
        intent.putExtra("app_package", app.packageName);
        intent.putExtra("app_downloads", app.downloads);
        intent.putExtra("app_versions", app.versionsCount);
        intent.putExtra("app_added_date", app.addedDate);
        startActivity(intent);
    }

    private void scanInstalledPackages() {
        new Thread(new Runnable() {
            public void run() {
                final Map<String, String> map = new HashMap<String, String>();
                try {
                    PackageManager pm = getPackageManager();
                    List<PackageInfo> installed = pm.getInstalledPackages(0);
                    for (PackageInfo info : installed) {
                        map.put(info.packageName, info.versionName != null ? info.versionName : "");
                    }
                } catch (Exception ignored) {}

                runOnUiThread(new Runnable() {
                    public void run() {
                        installedVersions = map;
                        adapter.notifyDataSetChanged();
                    }
                });
            }
        }).start();
    }

    private void showAppActionsDialog(final AppInfo app) {
        final boolean isFav = favoritesSet.contains(app.packageName);
        String[] items;
        if (isFav) {
            items = new String[]{"Download Latest", "Copy Package", "Remove from Favorites", "Share"};
        } else {
            items = new String[]{"Download Latest", "Copy Package", "Add to Favorites", "Share"};
        }

        new AlertDialog.Builder(this)
                .setTitle(app.name)
                .setItems(items, new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int which) {
                        switch (which) {
                            case 0:
                                quickDownload(app);
                                break;
                            case 1:
                                ClipboardManager cm = (ClipboardManager)
                                        getSystemService(CLIPBOARD_SERVICE);
                                cm.setText(app.packageName);
                                Toast.makeText(MainActivity.this,
                                        "Copied: " + app.packageName,
                                        Toast.LENGTH_SHORT).show();
                                break;
                            case 2:
                                if (isFav) {
                                    favoritesSet.remove(app.packageName);
                                    Toast.makeText(MainActivity.this,
                                            "Removed from Favorites",
                                            Toast.LENGTH_SHORT).show();
                                } else {
                                    favoritesSet.add(app.packageName);
                                    Toast.makeText(MainActivity.this,
                                            "Added to Favorites",
                                            Toast.LENGTH_SHORT).show();
                                }
                                saveFavorites(favoritesSet);
                                if (filterMode == 1) filterApps(searchInput.getText().toString());
                                break;
                            case 3:
                                shareApp(app);
                                break;
                        }
                    }
                })
                .show();
    }

    private void quickDownload(final AppInfo app) {
        Toast.makeText(this, "Downloading " + app.name + "...", Toast.LENGTH_SHORT).show();
        new AsyncTask<Void, Void, String>() {
            private String error;

            @Override
            protected String doInBackground(Void... params) {
                try {
                    File sd = Environment.getExternalStorageDirectory();
                    if (sd == null) return null;
                    File dir = new File(sd, "Download");
                    if (!dir.exists()) dir.mkdirs();
                    String fileName = (app.packageName != null ? app.packageName : "app") + "_v" + app.version + ".apk";
                    fileName = fileName.replaceAll("[^a-zA-Z0-9._-]", "_");
                    File dest = new File(dir, fileName);
                    String path = ApiClient.downloadFile(app.id, app.version, dest, null);
                    DownloadsActivity.addToHistory(MainActivity.this, app.packageName, app.name, app.version, path);
                    return path;
                } catch (Exception e) {
                    error = e.getMessage();
                    return null;
                }
            }

            @Override
            protected void onPostExecute(String path) {
                if (path != null) {
                    Toast.makeText(MainActivity.this, app.name + " downloaded", Toast.LENGTH_SHORT).show();
                    try {
                        Intent intent = new Intent(Intent.ACTION_VIEW);
                        intent.setDataAndType(Uri.fromFile(new File(path)),
                                "application/vnd.android.package-archive");
                        startActivity(intent);
                    } catch (Exception e) {
                        Toast.makeText(MainActivity.this,
                                "Can't open installer", Toast.LENGTH_LONG).show();
                    }
                } else {
                    String msg = error != null ? error : "Download failed";
                    Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
                }
            }
        }.execute();
    }

    private void shareApp(AppInfo app) {
        try {
            Intent share = new Intent(Intent.ACTION_SEND);
            share.setType("text/plain");
            String text = app.name + " (" + app.packageName + ") — DroidMarket\n" +
                    ApiClient.getBaseUrl() + "/app/" + app.packageName;
            share.putExtra(Intent.EXTRA_TEXT, text);
            startActivity(Intent.createChooser(share, "Share App"));
        } catch (Exception e) {
            Toast.makeText(this, "Share failed", Toast.LENGTH_SHORT).show();
        }
    }

    private Set<String> loadFavorites() {
        SharedPreferences prefs = getSharedPreferences(PREFS_FAVORITES, MODE_PRIVATE);
        String raw = prefs.getString("list", "");
        Set<String> set = new HashSet<String>();
        if (raw.length() > 0) {
            String[] parts = raw.split("\\|");
            for (String p : parts) {
                if (p.length() > 0) set.add(p);
            }
        }
        return set;
    }

    private void saveFavorites(Set<String> set) {
        SharedPreferences prefs = getSharedPreferences(PREFS_FAVORITES, MODE_PRIVATE);
        StringBuilder sb = new StringBuilder();
        for (String p : set) {
            if (sb.length() > 0) sb.append("|");
            sb.append(p);
        }
        prefs.edit().putString("list", sb.toString()).commit();
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
            intent.putExtra("app_added_date", app.addedDate);
            startActivity(intent);
        }
    }

    private void loadApps() {
        retryButton.setVisibility(View.GONE);
        if (loadAppsTask != null) {
            loadAppsTask.cancel(true);
            loadAppsTask = null;
        }
        loadAppsTask = new LoadAppsTask();
        loadAppsTask.execute();
    }

    private void filterApps(String query) {
        if (allApps == null) return;

        String q = query.toLowerCase().trim();
        ArrayList<AppInfo> source;

        if (filterMode == 1) {
            source = new ArrayList<AppInfo>();
            for (AppInfo app : allApps) {
                if (favoritesSet.contains(app.packageName)) {
                    source.add(app);
                }
            }
        } else if (filterMode == 2 && updatableApps != null) {
            source = updatableApps;
        } else {
            source = allApps;
        }

        ArrayList<AppInfo> filtered = new ArrayList<AppInfo>();

        if (q.length() == 0) {
            filtered.addAll(source);
        } else {
            for (AppInfo app : source) {
                if (app.name.toLowerCase().contains(q)
                        || app.packageName.toLowerCase().contains(q)) {
                    filtered.add(app);
                }
            }
        }

        adapter.setData(filtered);
        sectionHeader.setText(filtered.size() + " apps");
        sectionHeader.setVisibility(View.VISIBLE);
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, sortModeLabel(0)).setIcon(android.R.drawable.ic_menu_sort_alphabetically);
        menu.add(0, 2, 0, sortModeLabel(1)).setIcon(android.R.drawable.ic_menu_sort_by_size);
        menu.add(0, 3, 0, sortModeLabel(2)).setIcon(android.R.drawable.ic_menu_sort_by_size);
        menu.add(0, 4, 0, "Sort by Size").setIcon(android.R.drawable.ic_menu_sort_by_size);
        menu.add(0, 5, 0, "Refresh").setIcon(android.R.drawable.ic_menu_revert);
        menu.add(0, 6, 0, filterMode == 1 ? "All Apps" : "Favorites").setIcon(android.R.drawable.ic_menu_myplaces);
        menu.add(0, 7, 0, filterMode == 3 ? "All Apps" : "Installed Only").setIcon(0);
        menu.add(0, 8, 0, "Android Compatible").setIcon(0);
        menu.add(0, 9, 0, "Check Updates").setIcon(android.R.drawable.ic_menu_compass);
        menu.add(0, 10, 0, "Recently Viewed").setIcon(android.R.drawable.ic_menu_compass);
        menu.add(0, 11, 0, "Downloads").setIcon(R.drawable.ic_menu_bag_market);
        menu.add(0, 12, 0, "Installed Apps").setIcon(R.drawable.ic_menu_market_myapps);
        menu.add(0, 13, 0, "Auto-Refresh: " + (autoRefreshEnabled ? "ON" : "OFF")).setIcon(0);
        menu.add(0, 14, 0, "Export Favorites").setIcon(0);
        menu.add(0, 15, 0, "Import Favorites").setIcon(0);
        menu.add(0, 16, 0, "Clear All Data").setIcon(0);
        menu.add(0, 17, 0, "About").setIcon(android.R.drawable.ic_menu_info_details);
        String curTheme = ThemeManager.getCurrent(this);
        String themeLabel = "Market";
        if ("holo".equals(curTheme)) themeLabel = "Holo";
        else if ("material".equals(curTheme)) themeLabel = "Material";
        else if ("amoled".equals(curTheme)) themeLabel = "AMOLED";
        menu.add(0, 18, 0, "Theme: " + themeLabel).setIcon(android.R.drawable.ic_menu_gallery);
        menu.add(0, 19, 0, "Server: " + ServerManager.getActiveName(this))
                .setIcon(android.R.drawable.ic_menu_manage);
        menu.add(0, 20, 0, "Clear Cache").setIcon(0);
        return true;
    }

    private String sortModeLabel(int mode) {
        String prefix = mode == sortMode ? "> " : "";
        if (mode == 0) return prefix + "Sort by Name";
        if (mode == 1) return prefix + "Sort by Downloads";
        if (mode == 2) return prefix + "Sort by Newest";
        return prefix + "Sort by Size";
    }

    @Override
    public boolean onPrepareOptionsMenu(Menu menu) {
        try {
            menu.getItem(0).setTitle(sortModeLabel(0));
            menu.getItem(1).setTitle(sortModeLabel(1));
            menu.getItem(2).setTitle(sortModeLabel(2));
            menu.getItem(3).setTitle(sortModeLabel(3));
            menu.getItem(5).setTitle(filterMode == 1 ? "All Apps" : "Favorites");
            menu.getItem(6).setTitle(filterMode == 3 ? "All Apps" : "Installed Only");
            menu.getItem(12).setTitle("Auto-Refresh: " + (autoRefreshEnabled ? "ON" : "OFF"));
        } catch (Exception ignored) {}
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        switch (item.getItemId()) {
            case 1: sortMode = 0; sortApps(); return true;
            case 2: sortMode = 1; sortApps(); return true;
            case 3: sortMode = 2; sortApps(); return true;
            case 4: sortMode = 3; sortApps(); return true;
            case 5: loadApps(); return true;
            case 6:
                filterMode = (filterMode == 1) ? 0 : 1;
                filterApps(searchInput.getText().toString());
                return true;
            case 7:
                filterMode = (filterMode == 3) ? 0 : 3;
                filterApps(searchInput.getText().toString());
                return true;
            case 8:
                if (allApps == null) break;
                int deviceSdk = Build.VERSION.SDK_INT;
                ArrayList<AppInfo> compat = new ArrayList<AppInfo>();
                for (AppInfo a : allApps) {
                    try {
                        int min = Integer.parseInt(a.minSdk);
                        if (min <= deviceSdk) compat.add(a);
                    } catch (Exception e) {
                        compat.add(a);
                    }
                }
                Toast.makeText(this, compat.size() + "/" + allApps.size() + " compatible with API " + deviceSdk, Toast.LENGTH_LONG).show();
                return true;
            case 9: checkUpdates(); return true;
            case 10: showRecentlyViewed(); return true;
            case 11:
                startActivity(new Intent(MainActivity.this, DownloadsActivity.class));
                return true;
            case 12:
                startActivity(new Intent(MainActivity.this, InstalledAppsActivity.class));
                return true;
            case 13:
                autoRefreshEnabled = !autoRefreshEnabled;
                getSharedPreferences("settings", MODE_PRIVATE).edit().putBoolean("auto_refresh", autoRefreshEnabled).commit();
                if (autoRefreshEnabled) startAutoRefresh();
                else stopAutoRefresh();
                Toast.makeText(this, "Auto-Refresh: " + (autoRefreshEnabled ? "ON" : "OFF"), Toast.LENGTH_SHORT).show();
                return true;
            case 14: exportFavorites(); return true;
            case 15: importFavorites(); return true;
            case 16: clearAllData(); return true;
            case 17:
                startActivity(new Intent(MainActivity.this, AboutActivity.class));
                return true;
            case 18:
                String cur = ThemeManager.getCurrent(this);
                String next = ThemeManager.nextTheme(cur);
                ThemeManager.set(this, next);
                String label = "Holo";
                if ("material".equals(next)) label = "Material";
                else if ("amoled".equals(next)) label = "AMOLED";
                Toast.makeText(this, "Theme: " + label + " (restart required)", Toast.LENGTH_SHORT).show();
                return true;
            case 19: showServerDialog(); return true;
            case 20: imageLoader.clearCache(); Toast.makeText(this, "Cache cleared", Toast.LENGTH_SHORT).show(); return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void checkUpdates() {
        if (allApps == null || allApps.isEmpty()) {
            Toast.makeText(this, "Load app list first", Toast.LENGTH_SHORT).show();
            return;
        }
        new CheckUpdatesTask().execute();
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
        b.setPositiveButton("Delete", new DialogInterface.OnClickListener() {
            public void onClick(DialogInterface d, int which) {
                showDeleteServerDialog();
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

    private void showDeleteServerDialog() {
        final ArrayList<ServerConfig> servers = ServerManager.getServers(this);
        if (servers.size() <= 1) {
            Toast.makeText(this, "Cannot delete the last server",
                    Toast.LENGTH_SHORT).show();
            return;
        }
        final String[] names = new String[servers.size()];
        for (int i = 0; i < servers.size(); i++) {
            names[i] = servers.get(i).name + "  (" + servers.get(i).url + ")";
        }
        new AlertDialog.Builder(this)
                .setTitle("Delete Server")
                .setItems(names, new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int which) {
                        confirmDeleteServer(which);
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void confirmDeleteServer(final int index) {
        final ArrayList<ServerConfig> servers = ServerManager.getServers(this);
        final ServerConfig target = servers.get(index);
        new AlertDialog.Builder(this)
                .setTitle("Delete Server")
                .setMessage("Delete \"" + target.name + "\"?")
                .setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int which) {
                        servers.remove(index);
                        ServerManager.saveServers(MainActivity.this, servers);
                        String active = ServerManager.getActiveUrl(MainActivity.this);
                        if (target.url.equals(active)) {
                            ServerConfig first = servers.get(0);
                            ServerManager.setActiveUrl(MainActivity.this, first.url);
                            Toast.makeText(MainActivity.this,
                                    "Switched to: " + first.name,
                                    Toast.LENGTH_SHORT).show();
                            loadApps();
                        }
                        Toast.makeText(MainActivity.this,
                                "Deleted: " + target.name,
                                Toast.LENGTH_SHORT).show();
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
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
                            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                                Toast.makeText(MainActivity.this, "Invalid URL (must start with http:// or https://)", Toast.LENGTH_SHORT).show();
                                return;
                            }
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
        } else if (sortMode == 2) {
            Collections.sort(allApps, new Comparator<AppInfo>() {
                public int compare(AppInfo a, AppInfo b) {
                    return b.addedDate.compareTo(a.addedDate);
                }
            });
        } else {
            Collections.sort(allApps, new Comparator<AppInfo>() {
                public int compare(AppInfo a, AppInfo b) {
                    return a.name.compareToIgnoreCase(b.name);
                }
            });
        }
        if (filterMode == 1) favoritesSet = loadFavorites();
        filterApps(searchInput.getText().toString());
    }

    private class LoadAppsTask extends AsyncTask<Void, String, ArrayList<AppInfo>> {
        private ProgressDialog dialog;
        private String error;

        @Override
        protected void onPreExecute() {
            try {
                dialog = ProgressDialog.show(MainActivity.this, "",
                        getString(R.string.loading), true, false);
            } catch (Exception e) {
                dialog = null;
            }
        }

        @Override
        protected ArrayList<AppInfo> doInBackground(Void... params) {
            if (isCancelled()) return null;
            int maxRetries = 3;
            for (int attempt = 0; attempt < maxRetries; attempt++) {
                if (isCancelled()) return null;
                if (attempt > 0) {
                    if (isCancelled()) return null;
                    publishProgress("Retrying (" + attempt + "/" + (maxRetries - 1) + ")...");
                    try { Thread.sleep(2000); } catch (InterruptedException e) { return null; }
                }
                if (isCancelled()) return null;
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
            if (isCancelled()) return;

            if (dialog != null && dialog.isShowing()) {
                try { dialog.dismiss(); } catch (Exception ignored) {}
            }

            if (isFinishing()) return;

            if (result != null) {
                allApps = result;
                filterMode = 0;
                updatableApps = null;
                adapter.setData(result);
                sectionHeader.setText(result.size() + " apps");
                sectionHeader.setVisibility(View.VISIBLE);
                retryButton.setVisibility(View.GONE);
                scanInstalledPackages();

                if (result.size() == 0) {
                    Toast.makeText(MainActivity.this, "No apps on server",
                            Toast.LENGTH_LONG).show();
                }
            } else {
                showError(error != null ? error : "Connection failed");
                retryButton.setVisibility(View.VISIBLE);
            }
        }
    }

    private class CheckUpdatesTask extends AsyncTask<Void, Integer, ArrayList<AppInfo>> {
        private ProgressDialog dialog;

        @Override
        protected void onPreExecute() {
            try {
                dialog = ProgressDialog.show(MainActivity.this, "",
                        "Scanning installed apps...", true, false);
            } catch (Exception e) {
                dialog = null;
            }
        }

        @Override
        protected ArrayList<AppInfo> doInBackground(Void... params) {
            if (isCancelled()) return null;

            PackageManager pm = getPackageManager();
            List<PackageInfo> installed;
            try {
                installed = pm.getInstalledPackages(0);
            } catch (Exception e) {
                return null;
            }

            if (isCancelled()) return null;

            ArrayList<AppInfo> result = new ArrayList<AppInfo>();

            for (AppInfo marketApp : allApps) {
                if (isCancelled()) return null;

                String pkg = marketApp.packageName;
                String marketVer = marketApp.version;

                for (PackageInfo inst : installed) {
                    if (inst.packageName.equals(pkg)) {
                        String installedVer = inst.versionName;
                        if (installedVer != null && !installedVer.equals(marketVer)) {
                            result.add(marketApp);
                        }
                        break;
                    }
                }
            }

            return result;
        }

        @Override
        protected void onPostExecute(ArrayList<AppInfo> result) {
            if (isCancelled()) return;

            if (dialog != null && dialog.isShowing()) {
                try { dialog.dismiss(); } catch (Exception ignored) {}
            }

            if (isFinishing()) return;

            if (result != null) {
                if (result.isEmpty()) {
                    Toast.makeText(MainActivity.this,
                            "All apps are up to date!",
                            Toast.LENGTH_LONG).show();
                } else {
                    updatableApps = result;
                    filterMode = 2;
                    filterApps(searchInput.getText().toString());
                    Toast.makeText(MainActivity.this,
                            result.size() + " updates available",
                            Toast.LENGTH_SHORT).show();
                }
            } else {
                Toast.makeText(MainActivity.this,
                        "Failed to scan installed apps",
                        Toast.LENGTH_LONG).show();
            }
        }
    }

    private void showError(String msg) {
        if (isFinishing()) return;
        try {
            new AlertDialog.Builder(this)
                    .setTitle("Error")
                    .setMessage(msg)
                    .setPositiveButton("OK", null)
                    .show();
        } catch (Exception ignored) {}
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
            if (position >= 0 && position < apps.size()) {
                return apps.get(position);
            }
            return null;
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
                holder.type = (TextView) convertView.findViewById(R.id.app_type);
                holder.version = (TextView) convertView.findViewById(R.id.app_version);
                holder.size = (TextView) convertView.findViewById(R.id.app_size);
                holder.android = (TextView) convertView.findViewById(R.id.app_android);
                holder.date = (TextView) convertView.findViewById(R.id.app_date);
                holder.installBtn = (Button) convertView.findViewById(R.id.app_install_btn);
                convertView.setTag(holder);
            } else {
                holder = (ViewHolder) convertView.getTag();
            }

            if (position >= apps.size()) return convertView;
            AppInfo app = apps.get(position);
            MainActivity act = (MainActivity) context;
            holder.name.setText(app.name);

            if (app.type != null && !app.type.equals("apk")) {
                holder.type.setVisibility(View.VISIBLE);
                holder.type.setText(app.type.toUpperCase());
                if ("xapk".equals(app.type)) {
                    holder.type.setBackgroundColor(0xFF96AA39);
                } else if ("obb".equals(app.type)) {
                    holder.type.setBackgroundColor(0xFF666666);
                } else {
                    holder.type.setBackgroundColor(0xFF999999);
                }
            } else {
                holder.type.setVisibility(View.GONE);
            }

            holder.version.setText("v" + app.version);
            holder.size.setText(app.sizeFormatted);
            holder.android.setText("Android " + app.androidVer + "+");

            String installedVer = act.installedVersions != null
                    ? act.installedVersions.get(app.packageName) : null;
            if (installedVer != null) {
                if (!installedVer.equals(app.version)) {
                    holder.date.setText("Update: v" + app.version);
                    holder.date.setTextColor(0xFF96AA39);
                } else {
                    holder.date.setText("Installed");
                    holder.date.setTextColor(0xFF809130);
                }
                holder.date.setVisibility(View.VISIBLE);
            } else if (app.addedDate != null && app.addedDate.length() > 0) {
                String d = app.addedDate;
                if (d.length() > 10) d = d.substring(0, 10);
                holder.date.setText(d);
                holder.date.setTextColor(0xFF888888);
                holder.date.setVisibility(View.VISIBLE);
            } else {
                holder.date.setVisibility(View.GONE);
            }

            boolean showBtn = installedVer == null || !installedVer.equals(app.version);
            if (showBtn) {
                holder.installBtn.setVisibility(View.VISIBLE);
                holder.installBtn.setText(installedVer != null ? "UPDATE" : "FREE");
                final AppInfo fApp = app;
                holder.installBtn.setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) {
                        act.quickDownload(fApp);
                    }
                });
            } else {
                holder.installBtn.setVisibility(View.GONE);
            }

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
            TextView type;
            TextView version;
            TextView size;
            TextView android;
            TextView date;
            Button installBtn;
        }
    }
}
