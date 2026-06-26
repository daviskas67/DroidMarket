package com.droidmarket;

import android.app.Activity;
import android.os.Bundle;
import android.text.Html;
import android.text.method.LinkMovementMethod;
import android.widget.TextView;

public class AboutActivity extends Activity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        ThemeManager.apply(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.about);

        TextView info = (TextView) findViewById(R.id.about_info);
        info.setText(Html.fromHtml(
                "<b>DroidMarket</b> v2.0<br/><br/>"
                + "Android APK market client.<br/><br/>"
                + "Compatible with Android 1.6+<br/><br/>"
                + "Server: <a href=\"http://barbaros.serveousercontent.com\">barbaros.serveousercontent.com</a>"));
        info.setMovementMethod(LinkMovementMethod.getInstance());
    }
}
