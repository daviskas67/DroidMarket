package com.droidmarket;

import java.util.ArrayList;

import android.content.Context;
import android.content.SharedPreferences;

public class ServerManager {
    private static final String PREFS_NAME = "droidmarket";
    private static final String KEY_SERVERS = "servers";
    private static final String KEY_ACTIVE = "active_server";
    private static final String DEFAULT_NAME = "DroidMarket";
    private static final String DEFAULT_URL = "http://barbaros.serveousercontent.com";

    public static ArrayList<ServerConfig> getServers(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String json = prefs.getString(KEY_SERVERS, null);
        ArrayList<ServerConfig> list = new ArrayList<ServerConfig>();
        if (json != null) {
            try {
                String[] items = json.split("\\|");
                for (String item : items) {
                    String[] parts = item.split("\\~", 2);
                    if (parts.length == 2) {
                        list.add(new ServerConfig(parts[0], parts[1]));
                    }
                }
            } catch (Exception ignored) {}
        }
        if (list.isEmpty()) {
            list.add(new ServerConfig(DEFAULT_NAME, DEFAULT_URL));
        }
        return list;
    }

    public static void saveServers(Context context, ArrayList<ServerConfig> servers) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < servers.size(); i++) {
            if (i > 0) sb.append("|");
            sb.append(servers.get(i).name).append("~").append(servers.get(i).url);
        }
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit().putString(KEY_SERVERS, sb.toString()).commit();
    }

    public static String getActiveUrl(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        return prefs.getString(KEY_ACTIVE, DEFAULT_URL);
    }

    public static void setActiveUrl(Context context, String url) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit().putString(KEY_ACTIVE, url).commit();
        ApiClient.setBaseUrl(url);
    }

    public static String getActiveName(Context context) {
        String url = getActiveUrl(context);
        ArrayList<ServerConfig> servers = getServers(context);
        for (ServerConfig s : servers) {
            if (s.url.equals(url)) return s.name;
        }
        return DEFAULT_NAME;
    }
}
