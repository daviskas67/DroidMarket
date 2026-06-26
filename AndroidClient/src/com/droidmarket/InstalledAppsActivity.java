package com.droidmarket;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

import android.app.AlertDialog;
import android.app.ListActivity;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.graphics.drawable.Drawable;
import android.net.Uri;
import android.os.AsyncTask;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

public class InstalledAppsActivity extends ListActivity {

    private ArrayList<InstalledApp> allApps;
    private InstalledAdapter adapter;
    private EditText searchInput;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        ThemeManager.apply(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.installed_apps);

        searchInput = (EditText) findViewById(R.id.installed_search);
        adapter = new InstalledAdapter();
        setListAdapter(adapter);

        searchInput.addTextChangedListener(new TextWatcher() {
            public void afterTextChanged(Editable s) {
                filter(s.toString());
            }
            public void beforeTextChanged(CharSequence s, int s2, int s3, int s4) {}
            public void onTextChanged(CharSequence s, int s2, int s3, int s4) {}
        });

        loadApps();
    }

    private void loadApps() {
        new AsyncTask<Void, Void, ArrayList<InstalledApp>>() {
            protected ArrayList<InstalledApp> doInBackground(Void... p) {
                ArrayList<InstalledApp> list = new ArrayList<InstalledApp>();
                try {
                    PackageManager pm = getPackageManager();
                    List<PackageInfo> installed = pm.getInstalledPackages(0);
                    for (PackageInfo info : installed) {
                        InstalledApp a = new InstalledApp();
                        a.packageName = info.packageName;
                        a.versionName = info.versionName != null ? info.versionName : "?";
                        a.versionCode = info.versionCode;
                        try {
                            ApplicationInfo ai = pm.getApplicationInfo(info.packageName, 0);
                            a.name = pm.getApplicationLabel(ai).toString();
                            a.icon = ai.loadIcon(pm);
                        } catch (Exception e) {
                            a.name = info.packageName;
                            a.icon = null;
                        }
                        list.add(a);
                    }
                } catch (Exception ignored) {}
                Collections.sort(list, new Comparator<InstalledApp>() {
                    public int compare(InstalledApp a, InstalledApp b) {
                        return a.name.compareToIgnoreCase(b.name);
                    }
                });
                return list;
            }

            protected void onPostExecute(ArrayList<InstalledApp> result) {
                allApps = result;
                adapter.setData(result);
            }
        }.execute();
    }

    private void filter(String q) {
        if (allApps == null) return;
        q = q.toLowerCase().trim();
        ArrayList<InstalledApp> filtered = new ArrayList<InstalledApp>();
        for (InstalledApp a : allApps) {
            if (q.length() == 0 || a.name.toLowerCase().contains(q) || a.packageName.toLowerCase().contains(q)) {
                filtered.add(a);
            }
        }
        adapter.setData(filtered);
    }

    @Override
    protected void onListItemClick(ListView l, View v, int position, long id) {
        final InstalledApp app = adapter.getItem(position);
        if (app == null) return;

        new AlertDialog.Builder(this)
                .setTitle(app.name)
                .setItems(new String[]{"Open App", "App Info", "Search on Market", "Uninstall"},
                        new DialogInterface.OnClickListener() {
                            public void onClick(DialogInterface d, int w) {
                                PackageManager ppm = getPackageManager();
                                switch (w) {
                                    case 0:
                                        try {
                                            Intent i = ppm.getLaunchIntentForPackage(app.packageName);
                                            if (i != null) startActivity(i);
                                            else Toast.makeText(InstalledAppsActivity.this, "Cannot open", Toast.LENGTH_SHORT).show();
                                        } catch (Exception e) {
                                            Toast.makeText(InstalledAppsActivity.this, "Error", Toast.LENGTH_SHORT).show();
                                        }
                                        break;
                                    case 1:
                                        new AlertDialog.Builder(InstalledAppsActivity.this)
                                                .setTitle(app.name)
                                                .setMessage("Package: " + app.packageName + "\nVersion: " + app.versionName + " (" + app.versionCode + ")")
                                                .setPositiveButton("OK", null)
                                                .show();
                                        break;
                                    case 2:
                                        try {
                                            Intent i = new Intent(Intent.ACTION_VIEW);
                                            i.setData(Uri.parse(ApiClient.getBaseUrl() + "/app/" + app.packageName));
                                            startActivity(i);
                                        } catch (Exception e) {
                                            Toast.makeText(InstalledAppsActivity.this, "Error", Toast.LENGTH_SHORT).show();
                                        }
                                        break;
                                    case 3:
                                        try {
                                            Intent i = new Intent(Intent.ACTION_DELETE);
                                            i.setData(Uri.parse("package:" + app.packageName));
                                            startActivity(i);
                                        } catch (Exception e) {
                                            Toast.makeText(InstalledAppsActivity.this, "Cannot uninstall", Toast.LENGTH_SHORT).show();
                                        }
                                        break;
                                }
                            }
                        })
                .show();
    }

    private static class InstalledApp {
        String packageName;
        String name;
        String versionName;
        int versionCode;
        Drawable icon;
    }

    private class InstalledAdapter extends BaseAdapter {
        private ArrayList<InstalledApp> items = new ArrayList<InstalledApp>();
        private LayoutInflater inflater = LayoutInflater.from(InstalledAppsActivity.this);

        void setData(ArrayList<InstalledApp> d) { items = d != null ? d : new ArrayList<InstalledApp>(); notifyDataSetChanged(); }
        public int getCount() { return items.size(); }
        public InstalledApp getItem(int i) { return items.get(i); }
        public long getItemId(int i) { return i; }

        public View getView(int pos, View cv, ViewGroup p) {
            if (cv == null) {
                cv = inflater.inflate(android.R.layout.simple_list_item_2, p, false);
            }
            InstalledApp a = items.get(pos);
            ((TextView) cv.findViewById(android.R.id.text1)).setText(a.name);
            ((TextView) cv.findViewById(android.R.id.text2)).setText(a.packageName + "  v" + a.versionName);
            return cv;
        }
    }
}
