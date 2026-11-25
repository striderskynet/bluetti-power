package com.striderskynet.bluetti;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.UUID;

/**
 * Persistencia de estaciones, su último estado, el intervalo de sondeo y el
 * mapa de widgets. Sin dependencias: JSON de org.json + SharedPreferences.
 */
public final class DeviceStore {

    public static final int HINT_UNKNOWN = -1;
    public static final int HINT_PLAIN = 0;
    public static final int HINT_ENCRYPTED = 1;

    private static final String FILE = "bluetti";
    private static final String KEY_DEVICES = "devices_v3";
    private static final String KEY_STATES = "states_v3";
    private static final String KEY_WIDGETS = "widget_map_v3";
    private static final String KEY_INTERVAL = "interval_seconds";
    private static final String KEY_SERVICE = "service_enabled";
    private static final String KEY_DEMO = "demo_mode";
    private static final String KEY_MIGRATED = "migrated_v3";

    // Claves de la versión 0.2 para migrar
    private static final String OLD_ADDRESS = "address";
    private static final String OLD_NAME = "name";
    private static final String OLD_HINT = "encrypted_hint";
    private static final String OLD_PERCENT = "percent";
    private static final String OLD_AC_OUT = "ac_out";
    private static final String OLD_DC_OUT = "dc_out";
    private static final String OLD_AC_IN = "ac_in";
    private static final String OLD_DC_IN = "dc_in";
    private static final String OLD_TYPE = "device_type";
    private static final String OLD_UPDATED = "updated";
    private static final String OLD_ERROR = "error";
    private static final String OLD_ENCRYPTED = "encrypted";

    private DeviceStore() {
    }

    public static SharedPreferences sp(Context context) {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    // ---------------------------------------------------------------- estaciones

    public static synchronized List<Device> devices(Context context) {
        migrate(context);
        List<Device> devices = new ArrayList<>();
        String raw = sp(context).getString(KEY_DEVICES, "[]");
        try {
            JSONArray array = new JSONArray(raw);
            for (int i = 0; i < array.length(); i++) {
                Device device = Device.fromJson(array.getJSONObject(i));
                if (device.id != null && !device.id.isEmpty()) {
                    devices.add(device);
                }
            }
        } catch (JSONException ignored) {
            // lista corrupta: se ignora
        }
        return devices;
    }

    private static void saveDevices(Context context, List<Device> devices) {
        JSONArray array = new JSONArray();
        for (Device device : devices) {
            try {
                array.put(device.toJson());
            } catch (JSONException ignored) {
                // no debería pasar
            }
        }
        sp(context).edit().putString(KEY_DEVICES, array.toString()).apply();
    }

    public static synchronized Device find(Context context, String id) {
        if (id == null || id.isEmpty()) {
            return null;
        }
        for (Device device : devices(context)) {
            if (id.equals(device.id)) {
                return device;
            }
        }
        return null;
    }

    /** Añade una estación o actualiza la existente con la misma dirección. */
    public static synchronized Device addOrUpdate(Context context, String address, String name, int hint) {
        List<Device> devices = devices(context);
        String normalized = address == null ? "" : address.trim().toUpperCase();
        for (Device device : devices) {
            if (device.address.equalsIgnoreCase(normalized)) {
                device.hint = hint;
                if (name != null && !name.trim().isEmpty()) {
                    // No pisar el alias del usuario; solo el nombre anunciado.
                    device = new Device(device.id, normalized, name.trim(), device.alias, hint);
                    devices.set(indexOf(devices, device.id), device);
                }
                saveDevices(context, devices);
                return device;
            }
        }
        Device device = new Device(UUID.randomUUID().toString(), normalized,
                name == null ? "" : name.trim(), "", hint);
        devices.add(device);
        saveDevices(context, devices);
        return device;
    }

    private static int indexOf(List<Device> devices, String id) {
        for (int i = 0; i < devices.size(); i++) {
            if (devices.get(i).id.equals(id)) {
                return i;
            }
        }
        return -1;
    }

    public static synchronized void rename(Context context, String id, String alias) {
        List<Device> devices = devices(context);
        int index = indexOf(devices, id);
        if (index < 0) {
            return;
        }
        Device old = devices.get(index);
        devices.set(index, new Device(old.id, old.address, old.name, alias, old.hint));
        saveDevices(context, devices);
    }

    public static synchronized void updateAddress(Context context, String id, String address) {
        List<Device> devices = devices(context);
        int index = indexOf(devices, id);
        if (index < 0) {
            return;
        }
        Device old = devices.get(index);
        devices.set(index, new Device(old.id, address.trim().toUpperCase(), old.name, old.alias, old.hint));
        saveDevices(context, devices);
    }

    public static synchronized void remove(Context context, String id) {
        List<Device> devices = devices(context);
        int index = indexOf(devices, id);
        if (index >= 0) {
            devices.remove(index);
            saveDevices(context, devices);
        }
        try {
            JSONObject states = new JSONObject(sp(context).getString(KEY_STATES, "{}"));
            states.remove(id);
            sp(context).edit().putString(KEY_STATES, states.toString()).apply();
        } catch (JSONException ignored) {
            // nada
        }
        // Quitar los widgets asociados a esta estación
        SharedPreferences preferences = sp(context);
        SharedPreferences.Editor editor = preferences.edit();
        try {
            JSONObject map = new JSONObject(preferences.getString(KEY_WIDGETS, "{}"));
            Iterator<String> keys = map.keys();
            List<String> toRemove = new ArrayList<>();
            while (keys.hasNext()) {
                String key = keys.next();
                if (id.equals(map.optString(key))) {
                    toRemove.add(key);
                }
            }
            for (String key : toRemove) {
                map.remove(key);
            }
            editor.putString(KEY_WIDGETS, map.toString());
        } catch (JSONException ignored) {
            // nada
        }
        editor.apply();
    }

    // ------------------------------------------------------------------ estados

    public static synchronized void saveState(Context context, String id, Reading reading) {
        SharedPreferences preferences = sp(context);
        JSONObject states;
        try {
            states = new JSONObject(preferences.getString(KEY_STATES, "{}"));
        } catch (JSONException exc) {
            states = new JSONObject();
        }
        try {
            states.put(id, readingToJson(reading));
        } catch (JSONException ignored) {
            return;
        }
        preferences.edit().putString(KEY_STATES, states.toString()).apply();
    }

    public static synchronized Reading state(Context context, String id) {
        Reading reading = new Reading();
        try {
            JSONObject states = new JSONObject(sp(context).getString(KEY_STATES, "{}"));
            if (states.has(id)) {
                reading = readingFromJson(states.getJSONObject(id));
            }
        } catch (JSONException ignored) {
            // sin estado
        }
        return reading;
    }

    private static JSONObject readingToJson(Reading reading) throws JSONException {
        JSONObject json = new JSONObject();
        json.put("percent", reading.percent);
        json.put("ac_out", reading.acOut);
        json.put("dc_out", reading.dcOut);
        json.put("ac_in", reading.acIn);
        json.put("dc_in", reading.dcIn);
        json.put("grid_voltage", reading.gridVoltage);
        json.put("type", reading.deviceType == null ? "" : reading.deviceType);
        json.put("serial", reading.serialNumber == null ? "" : reading.serialNumber);
        json.put("encrypted", reading.encrypted);
        json.put("demo", reading.demo);
        json.put("error", reading.error == null ? JSONObject.NULL : reading.error);
        json.put("time", reading.time);
        json.put("address", reading.address == null ? "" : reading.address);
        return json;
    }

    private static Reading readingFromJson(JSONObject json) {
        Reading reading = new Reading();
        reading.percent = json.optInt("percent", -1);
        reading.acOut = json.optInt("ac_out", -1);
        reading.dcOut = json.optInt("dc_out", -1);
        reading.acIn = json.optInt("ac_in", -1);
        reading.dcIn = json.optInt("dc_in", -1);
        reading.gridVoltage = json.optInt("grid_voltage", -1);
        reading.deviceType = json.optString("type", "");
        reading.serialNumber = json.optString("serial", "");
        reading.encrypted = json.optBoolean("encrypted", false);
        reading.demo = json.optBoolean("demo", false);
        reading.error = json.isNull("error") ? null : json.optString("error", null);
        reading.time = json.optLong("time", 0L);
        reading.address = json.optString("address", "");
        return reading;
    }

    // ---------------------------------------------------------------- ajustes

    public static int intervalSeconds(Context context) {
        int value = sp(context).getInt(KEY_INTERVAL, 300);
        return Math.max(60, Math.min(value, 3600));
    }

    public static void setIntervalSeconds(Context context, int seconds) {
        int value = Math.max(60, Math.min(seconds, 3600));
        sp(context).edit().putInt(KEY_INTERVAL, value).apply();
    }

    public static boolean serviceEnabled(Context context) {
        return sp(context).getBoolean(KEY_SERVICE, false);
    }

    public static void setServiceEnabled(Context context, boolean enabled) {
        sp(context).edit().putBoolean(KEY_SERVICE, enabled).apply();
    }

    public static boolean isDemo(Context context) {
        return sp(context).getBoolean(KEY_DEMO, false);
    }

    public static void setDemo(Context context, boolean demo) {
        sp(context).edit().putBoolean(KEY_DEMO, demo).apply();
    }

    // ---------------------------------------------------------------- widgets

    public static String widgetDevice(Context context, int appWidgetId) {
        try {
            JSONObject map = new JSONObject(sp(context).getString(KEY_WIDGETS, "{}"));
            return map.optString(String.valueOf(appWidgetId), "");
        } catch (JSONException exc) {
            return "";
        }
    }

    public static void setWidgetDevice(Context context, int appWidgetId, String deviceId) {
        SharedPreferences preferences = sp(context);
        JSONObject map;
        try {
            map = new JSONObject(preferences.getString(KEY_WIDGETS, "{}"));
        } catch (JSONException exc) {
            map = new JSONObject();
        }
        try {
            map.put(String.valueOf(appWidgetId), deviceId);
        } catch (JSONException ignored) {
            return;
        }
        preferences.edit().putString(KEY_WIDGETS, map.toString()).apply();
    }

    public static void removeWidget(Context context, int appWidgetId) {
        SharedPreferences preferences = sp(context);
        JSONObject map;
        try {
            map = new JSONObject(preferences.getString(KEY_WIDGETS, "{}"));
        } catch (JSONException exc) {
            return;
        }
        map.remove(String.valueOf(appWidgetId));
        preferences.edit().putString(KEY_WIDGETS, map.toString()).apply();
    }

    // --------------------------------------------------------------- migración

    private static synchronized void migrate(Context context) {
        SharedPreferences preferences = sp(context);
        if (preferences.getBoolean(KEY_MIGRATED, false)) {
            return;
        }
        String oldAddress = preferences.getString(OLD_ADDRESS, "");
        int oldHint = preferences.getInt(OLD_HINT, HINT_UNKNOWN);
        String oldName = preferences.getString(OLD_NAME, "");
        List<Device> devices = new ArrayList<>();
        String deviceId = "";
        if (oldAddress != null && !oldAddress.trim().isEmpty()) {
            Device device = new Device(UUID.randomUUID().toString(), oldAddress.trim().toUpperCase(),
                    oldName == null ? "" : oldName, "", oldHint);
            devices.add(device);
            deviceId = device.id;
            int percent = preferences.getInt(OLD_PERCENT, -1);
            if (percent >= 0) {
                Reading reading = new Reading();
                reading.percent = percent;
                reading.acOut = preferences.getInt(OLD_AC_OUT, -1);
                reading.dcOut = preferences.getInt(OLD_DC_OUT, -1);
                reading.acIn = preferences.getInt(OLD_AC_IN, -1);
                reading.dcIn = preferences.getInt(OLD_DC_IN, -1);
                reading.deviceType = preferences.getString(OLD_TYPE, "");
                reading.encrypted = preferences.getBoolean(OLD_ENCRYPTED, false);
                reading.time = preferences.getLong(OLD_UPDATED, 0L);
                reading.error = preferences.getString(OLD_ERROR, null);
                reading.address = oldAddress.trim().toUpperCase();
                saveState(context, deviceId, reading);
            }
        }
        saveDevices(context, devices);
        preferences.edit().putBoolean(KEY_MIGRATED, true).apply();
    }
}
