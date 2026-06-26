package com.droidmarket;

import android.app.Activity;
import android.content.SharedPreferences;

public class ThemeManager {
    private static final String PREFS_NAME = "droidmarket";
    private static final String KEY_THEME = "theme";

    public static final String THEME_HOLO = "holo";
    public static final String THEME_MATERIAL = "material";
    public static final String THEME_AMOLED = "amoled";

    public static void apply(Activity activity) {
        SharedPreferences prefs = activity.getSharedPreferences(PREFS_NAME, Activity.MODE_PRIVATE);
        String theme = prefs.getString(KEY_THEME, THEME_HOLO);
        if (THEME_MATERIAL.equals(theme)) {
            activity.setTheme(R.style.Theme_DroidMarket_Material);
        } else if (THEME_AMOLED.equals(theme)) {
            activity.setTheme(R.style.Theme_DroidMarket_AMOLED);
        } else {
            activity.setTheme(R.style.Theme_DroidMarket);
        }
    }

    public static String getCurrent(Activity activity) {
        SharedPreferences prefs = activity.getSharedPreferences(PREFS_NAME, Activity.MODE_PRIVATE);
        return prefs.getString(KEY_THEME, THEME_HOLO);
    }

    public static void set(Activity activity, String theme) {
        SharedPreferences prefs = activity.getSharedPreferences(PREFS_NAME, Activity.MODE_PRIVATE);
        prefs.edit().putString(KEY_THEME, theme).commit();
    }

    public static String nextTheme(String current) {
        if (THEME_MATERIAL.equals(current)) return THEME_AMOLED;
        if (THEME_AMOLED.equals(current)) return THEME_HOLO;
        return THEME_MATERIAL;
    }
}
