package com.striderskynet.bluetti;

import android.content.Context;
import android.content.SharedPreferences;

/** Preferencias y último estado conocido (lo comparten la app, el servicio y el widget). */
public final class Prefs {

    public static final int HINT_UNKNOWN = -1;
    public static final int HINT_PLAIN = 0;
    public static final int HINT_ENCRYPTED = 1;

    private static final String FILE = "bluetti";
    private static final String KEY_ADDRESS = "address";
    private static final String KEY_NAME = "name";
    private static final String KEY_HINT = "encrypted_hint";
    private static final String KEY_ENABLED = "service_enabled";
    private static final String KEY_DEMO_MODE = "demo_mode";
    private static final String KEY_DEMO_READING = "demo_reading";
    private static final String KEY_PERCENT = "percent";
    private static final String KEY_AC_OUT = "ac_out";
    private static final String KEY_DC_OUT = "dc_out";
    private static final String KEY_AC_IN = "ac_in";
    private static final String KEY_DC_IN = "dc_in";
    private static final String KEY_TYPE = "device_type";
    private static final String KEY_UPDATED = "updated";
    private static final String KEY_ERROR = "error";
    private static final String KEY_ENCRYPTED = "encrypted";

    private Prefs() {
    }

    public static SharedPreferences sp(Context context) {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public static String address(Context context) {
        return sp(context).getString(KEY_ADDRESS, "");
    }

    public static String name(Context context) {
        return sp(context).getString(KEY_NAME, "");
    }

    public static int hint(Context context) {
        return sp(context).getInt(KEY_HINT, HINT_UNKNOWN);
    }

    public static void setDevice(Context context, String address, String name, int hint) {
        sp(context).edit()
                .putString(KEY_ADDRESS, address == null ? "" : address.toUpperCase())
                .putString(KEY_NAME, name == null ? "" : name)
                .putInt(KEY_HINT, hint)
                .apply();
    }

    public static void setAddress(Context context, String address) {
        sp(context).edit().putString(KEY_ADDRESS, address == null ? "" : address.toUpperCase()).apply();
    }

    public static boolean enabled(Context context) {
        return sp(context).getBoolean(KEY_ENABLED, false);
    }

    public static void setEnabled(Context context, boolean enabled) {
        sp(context).edit().putBoolean(KEY_ENABLED, enabled).apply();
    }

    public static boolean isDemo(Context context) {
        return sp(context).getBoolean(KEY_DEMO_MODE, false);
    }

    public static void setDemo(Context context, boolean demo) {
        sp(context).edit().putBoolean(KEY_DEMO_MODE, demo).apply();
    }

    public static void saveReading(Context context, Reading reading) {
        SharedPreferences.Editor editor = sp(context).edit();
        editor.putInt(KEY_PERCENT, reading.percent);
        editor.putInt(KEY_AC_OUT, reading.acOut);
        editor.putInt(KEY_DC_OUT, reading.dcOut);
        editor.putInt(KEY_AC_IN, reading.acIn);
        editor.putInt(KEY_DC_IN, reading.dcIn);
        editor.putString(KEY_TYPE, reading.deviceType == null ? "" : reading.deviceType);
        editor.putLong(KEY_UPDATED, reading.time);
        editor.putBoolean(KEY_ENCRYPTED, reading.encrypted);
        editor.putBoolean(KEY_DEMO_READING, reading.demo);
        if (reading.error == null) {
            editor.remove(KEY_ERROR);
        } else {
            editor.putString(KEY_ERROR, reading.error);
        }
        editor.apply();
    }

    public static Reading loadReading(Context context) {
        SharedPreferences preferences = sp(context);
        Reading reading = new Reading();
        reading.percent = preferences.getInt(KEY_PERCENT, -1);
        reading.acOut = preferences.getInt(KEY_AC_OUT, -1);
        reading.dcOut = preferences.getInt(KEY_DC_OUT, -1);
        reading.acIn = preferences.getInt(KEY_AC_IN, -1);
        reading.dcIn = preferences.getInt(KEY_DC_IN, -1);
        reading.deviceType = preferences.getString(KEY_TYPE, "");
        reading.time = preferences.getLong(KEY_UPDATED, 0L);
        reading.encrypted = preferences.getBoolean(KEY_ENCRYPTED, false);
        reading.demo = preferences.getBoolean(KEY_DEMO_READING, false);
        reading.error = preferences.getString(KEY_ERROR, null);
        return reading;
    }

    public static boolean hasData(Context context) {
        return loadReading(context).time > 0L;
    }
}
