package com.droidmarket;

import java.io.BufferedInputStream;
import java.io.InputStream;
import java.lang.ref.WeakReference;
import java.util.HashMap;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.AsyncTask;
import android.widget.ImageView;

import org.apache.http.HttpEntity;
import org.apache.http.HttpResponse;
import org.apache.http.client.methods.HttpGet;

public class ImageLoader {

    private HashMap<String, Bitmap> cache;
    private static final int MAX_CACHE = 100;
    private static final String TAG_KEY = "image_loader_url";

    public ImageLoader() {
        cache = new HashMap<String, Bitmap>();
    }

    public synchronized void clearCache() {
        cache.clear();
    }

    public void load(String url, ImageView view) {
        if (url == null || url.length() == 0) {
            view.setImageResource(android.R.drawable.sym_def_app_icon);
            return;
        }
        if (cache.containsKey(url)) {
            Bitmap bm = cache.get(url);
            if (bm != null) {
                view.setImageBitmap(bm);
                return;
            }
        }

        Object pending = view.getTag();
        if (pending instanceof LoadTask) {
            ((LoadTask) pending).cancel(true);
        }

        view.setImageResource(android.R.drawable.sym_def_app_icon);
        LoadTask task = new LoadTask(view, url);
        view.setTag(task);
        task.execute();
    }

    private class LoadTask extends AsyncTask<Void, Void, Bitmap> {
        private WeakReference<ImageView> viewRef;
        private String url;

        public LoadTask(ImageView view, String url) {
            this.viewRef = new WeakReference<ImageView>(view);
            this.url = url;
        }

        @Override
        protected Bitmap doInBackground(Void... params) {
            try {
                HttpGet request = new HttpGet(url);
                HttpResponse response = ApiClient.getSharedClient().execute(request);
                if (response.getStatusLine().getStatusCode() != 200) {
                    return null;
                }
                HttpEntity entity = response.getEntity();
                if (entity == null) {
                    return null;
                }

                InputStream is = new BufferedInputStream(entity.getContent(), 8192);
                try {
                    BitmapFactory.Options opts = new BitmapFactory.Options();
                    opts.inSampleSize = 2;
                    Bitmap bm;
                    try {
                        bm = BitmapFactory.decodeStream(is, null, opts);
                    } catch (OutOfMemoryError e) {
                        return null;
                    }
                    if (bm == null) return null;

                    if (bm.getWidth() > 128 || bm.getHeight() > 128) {
                        float scale = Math.min(128f / bm.getWidth(), 128f / bm.getHeight());
                        int w = Math.round(bm.getWidth() * scale);
                        int h = Math.round(bm.getHeight() * scale);
                        Bitmap scaled;
                        try {
                            scaled = Bitmap.createScaledBitmap(bm, w, h, true);
                        } catch (OutOfMemoryError e) {
                            return bm;
                        }
                        if (scaled != bm) { bm.recycle(); }
                        bm = scaled;
                    }
                    return bm;
                } finally {
                    try { is.close(); } catch (Exception ignored) {}
                    try { entity.consumeContent(); } catch (Exception ignored) {}
                }
            } catch (Exception e) {
                return null;
            }
        }

        @Override
        protected void onPostExecute(Bitmap bm) {
            if (isCancelled()) return;
            if (bm == null) return;

            ImageView view = viewRef.get();
            if (view == null) return;

            Object tag = view.getTag();
            if (tag != this) return;

            synchronized (ImageLoader.this) {
                if (cache.size() >= MAX_CACHE) {
                    cache.clear();
                }
                cache.put(url, bm);
            }
            view.setImageBitmap(bm);
        }
    }
}
