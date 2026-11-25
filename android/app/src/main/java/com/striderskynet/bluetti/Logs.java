package com.striderskynet.bluetti;

import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Registro sencillo en archivo (se muestra desde la app). */
public final class Logs {

    private static final long MAX_BYTES = 64 * 1024;
    private static final SimpleDateFormat FORMAT =
            new SimpleDateFormat("dd/MM HH:mm:ss", Locale.getDefault());

    private Logs() {
    }

    private static File file(Context context) {
        return new File(context.getFilesDir(), "bluetti.log");
    }

    public static synchronized void log(Context context, String message) {
        try {
            File target = file(context);
            if (target.length() > MAX_BYTES) {
                target.delete();
            }
            String line = FORMAT.format(new Date()) + "  " + message + "\n";
            FileOutputStream out = new FileOutputStream(target, true);
            try {
                out.write(line.getBytes("UTF-8"));
            } finally {
                out.close();
            }
        } catch (IOException ignored) {
            // el registro nunca debe romper la app
        }
    }

    public static synchronized String tail(Context context) {
        File target = file(context);
        if (!target.exists()) {
            return "Sin actividad todavía.";
        }
        try {
            FileInputStream in = new FileInputStream(target);
            try {
                int size = (int) target.length();
                byte[] data = new byte[size];
                int read = 0;
                while (read < size) {
                    int count = in.read(data, read, size - read);
                    if (count <= 0) {
                        break;
                    }
                    read += count;
                }
                return new String(data, 0, read, "UTF-8");
            } finally {
                in.close();
            }
        } catch (IOException exc) {
            return "No se pudo leer el registro: " + exc.getMessage();
        }
    }

    public static synchronized void clear(Context context) {
        file(context).delete();
    }
}
