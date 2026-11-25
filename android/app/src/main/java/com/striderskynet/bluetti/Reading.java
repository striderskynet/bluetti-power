package com.striderskynet.bluetti;

/** Resultado de una lectura del equipo. Los valores desconocidos valen -1. */
public final class Reading {

    public int percent = -1;
    public int acOut = -1;
    public int dcOut = -1;
    public int acIn = -1;
    public int dcIn = -1;
    public String deviceType = "";
    public String serialNumber = "";
    public boolean encrypted;
    public boolean demo;
    public String error;
    public long time;
    public String address = "";

    public boolean ok() {
        return error == null && percent >= 0;
    }

    public int totalOut() {
        int ac = Math.max(0, acOut);
        int dc = Math.max(0, dcOut);
        return ac + dc;
    }

    public int totalIn() {
        int ac = Math.max(0, acIn);
        int dc = Math.max(0, dcIn);
        return ac + dc;
    }

    public String state() {
        if (error != null) {
            return "sin conexión";
        }
        boolean in = totalIn() > 5;
        boolean out = totalOut() > 5;
        if (in && out) {
            return "entrada y salida";
        }
        if (in) {
            return "cargando";
        }
        if (out) {
            return "descargando";
        }
        return "en reposo";
    }

    /** Texto corto y estable para el estado (sin datos de error). */
    public String shortState() {
        if (error != null) {
            return "sin conexión";
        }
        return state();
    }
}
