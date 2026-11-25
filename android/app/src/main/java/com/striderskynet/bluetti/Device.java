package com.striderskynet.bluetti;

import org.json.JSONException;
import org.json.JSONObject;

/** Una estación BLUETTI configurada en la app. */
public final class Device {

    public final String id;
    public String address;
    public final String name;
    public String alias;
    public int hint;

    public Device(String id, String address, String name, String alias, int hint) {
        this.id = id;
        this.address = address == null ? "" : address.toUpperCase();
        this.name = name == null ? "" : name;
        this.alias = alias == null ? "" : alias;
        this.hint = hint;
    }

    /** Nombre a mostrar: alias del usuario, modelo (con sufijo si hay varios) o dirección. */
    public String displayName() {
        if (alias != null && !alias.trim().isEmpty()) {
            return alias.trim();
        }
        String model = model();
        if (!model.isEmpty()) {
            String source = name == null ? "" : name.trim();
            if (source.length() > model.length() + 4) {
                String suffix = source.substring(source.length() - 4);
                return model + "·" + suffix;
            }
            return model;
        }
        if (name != null && !name.isEmpty()) {
            return name;
        }
        return address;
    }

    /** Modelo deducido del nombre anunciado (AC180P2507... -> AC180P). */
    public String model() {
        String source = name == null ? "" : name.trim();
        if (source.isEmpty()) {
            return "";
        }
        int end = source.length();
        for (int i = 0; i < source.length(); i++) {
            if (Character.isDigit(source.charAt(i))) {
                end = i;
                break;
            }
        }
        String model = source.substring(0, end).trim();
        return model.length() >= 3 ? model : "";
    }

    public String labelShort() {
        String model = model();
        if (!model.isEmpty()) {
            return model;
        }
        return displayName();
    }

    /** Capacidad nominal de batería según el modelo (Wh, aproximada). */
    public int capacityWh() {
        String model = model().toUpperCase();
        if (model.startsWith("AC180")) {
            return 1152;
        }
        if (model.startsWith("AC200PL")) {
            return 2304;
        }
        if (model.startsWith("AC200")) {
            return 2048;
        }
        if (model.startsWith("AC300")) {
            return 3072;
        }
        if (model.startsWith("AC70P")) {
            return 864;
        }
        if (model.startsWith("AC70")) {
            return 768;
        }
        if (model.startsWith("AC60P")) {
            return 504;
        }
        if (model.startsWith("AC60")) {
            return 403;
        }
        if (model.startsWith("AC50B")) {
            return 448;
        }
        if (model.startsWith("AC2A")) {
            return 204;
        }
        if (model.startsWith("AP300")) {
            return 288;
        }
        if (model.startsWith("EB3A")) {
            return 268;
        }
        if (model.startsWith("EB70")) {
            return 716;
        }
        if (model.startsWith("EP500")) {
            return 5100;
        }
        return 1152;
    }

    public JSONObject toJson() throws JSONException {
        JSONObject json = new JSONObject();
        json.put("id", id);
        json.put("address", address);
        json.put("name", name);
        json.put("alias", alias);
        json.put("hint", hint);
        return json;
    }

    public static Device fromJson(JSONObject json) {
        return new Device(
                json.optString("id", ""),
                json.optString("address", ""),
                json.optString("name", ""),
                json.optString("alias", ""),
                json.optInt("hint", DeviceStore.HINT_UNKNOWN)
        );
    }
}
