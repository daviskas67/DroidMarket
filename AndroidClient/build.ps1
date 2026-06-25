$ErrorActionPreference = "Stop"

$ANDROID_HOME = "C:\Android"
$PLATFORM = "$ANDROID_HOME\platforms\android-7"
$BUILD_TOOLS_OLD = "$ANDROID_HOME\build-tools\19.1.0"
$BUILD_TOOLS = "$ANDROID_HOME\build-tools\35.0.0"
$JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-21.0.10.7-hotspot"
$PROJECT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BUILD_DIR = "$PROJECT_DIR\build"
$GEN_DIR = "$PROJECT_DIR\gen"
$SRC_DIR = "$PROJECT_DIR\src"
$RES_DIR = "$PROJECT_DIR\res"
$ANDROID_JAR = "$PLATFORM\android.jar"
$AAPT = "$BUILD_TOOLS_OLD\aapt.exe"
$D8_JAR = "$BUILD_TOOLS\lib\d8.jar"
$ZIPALIGN = "$BUILD_TOOLS_OLD\zipalign.exe"
$JAVAC = "$JAVA_HOME\bin\javac.exe"
$JAVA_CMD = "$JAVA_HOME\bin\java.exe"
$KEYTOOL = "$JAVA_HOME\bin\keytool.exe"
$JARSIGNER = "$JAVA_HOME\bin\jarsigner.exe"

$env:JAVA_HOME = $JAVA_HOME

Write-Host "=== Step 1: Cleaning build directories ==="
Remove-Item -Recurse -Force "$BUILD_DIR\*" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$GEN_DIR\*" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path "$BUILD_DIR\classes" -Force | Out-Null
New-Item -ItemType Directory -Path "$BUILD_DIR\dex" -Force | Out-Null

Write-Host "=== Step 2: Generating R.java with aapt ==="
& $AAPT package -f -m -J "$GEN_DIR" -M "$PROJECT_DIR\AndroidManifest.xml" -S "$RES_DIR" -I "$ANDROID_JAR"
if ($LASTEXITCODE -ne 0) { throw "aapt failed" }

Write-Host "=== Step 3: Compiling Java sources ==="
$JAVA_FILES = @(Get-ChildItem -Recurse -Filter "*.java" -Path "$SRC_DIR" | ForEach-Object { $_.FullName })
$JAVA_FILES += @(Get-ChildItem -Recurse -Filter "*.java" -Path "$GEN_DIR" | ForEach-Object { $_.FullName })

& $JAVAC -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d "$BUILD_DIR\classes" @($JAVA_FILES)
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

Write-Host "=== Step 4: Creating classes JAR ==="
& "$JAVA_HOME\bin\jar.exe" cf "$BUILD_DIR\classes.jar" -C "$BUILD_DIR\classes" .
if ($LASTEXITCODE -ne 0) { throw "jar failed" }

Write-Host "=== Step 5: Converting to DEX with d8 ==="
& $JAVA_CMD -Xmx1024M -Xss1m -cp "$D8_JAR" com.android.tools.r8.D8 --min-api 4 --output "$BUILD_DIR\dex" --lib "$ANDROID_JAR" "$BUILD_DIR\classes.jar"
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Write-Host "=== Step 6: Creating unsigned APK ==="
& $AAPT package -f -M "$PROJECT_DIR\AndroidManifest.xml" -S "$RES_DIR" -I "$ANDROID_JAR" -F "$BUILD_DIR\unsigned.apk"
if ($LASTEXITCODE -ne 0) { throw "aapt package failed" }

Write-Host "=== Step 7: Adding DEX to APK ==="
Push-Location "$BUILD_DIR\dex"
& $AAPT add "$BUILD_DIR\unsigned.apk" classes.dex
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "aapt add failed" }

Write-Host "=== Step 8: Creating debug keystore ==="
if (-not (Test-Path "$PROJECT_DIR\debug.keystore")) {
    & $KEYTOOL -genkey -v -keystore "$PROJECT_DIR\debug.keystore" -alias androiddebugkey -storepass android -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US"
}

Write-Host "=== Step 9: Signing APK with SHA1 (Android 1.6 compatible) ==="
$SEC_OVERRIDE = "$env:TEMP\java.security.override"
@"
jdk.jar.disabledAlgorithms=
jdk.security.legacyAlgorithms=SHA1withRSA, SHA1
"@ | Set-Content -Path $SEC_OVERRIDE -Encoding ASCII -Force
& $JARSIGNER -J"-Djava.security.properties=$SEC_OVERRIDE" -keystore "$PROJECT_DIR\debug.keystore" -storepass android -keypass android -sigalg SHA1withRSA -digestalg SHA1 -signedjar "$BUILD_DIR\signed.apk" "$BUILD_DIR\unsigned.apk" androiddebugkey
if ($LASTEXITCODE -ne 0) { throw "jarsigner failed" }

Write-Host "=== Step 10: Aligning APK ==="
& $ZIPALIGN -f 4 "$BUILD_DIR\signed.apk" "$BUILD_DIR\DroidMarket.apk"
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

Write-Host "=== DONE ==="
Write-Host "APK: $BUILD_DIR\DroidMarket.apk"
$size = (Get-Item "$BUILD_DIR\DroidMarket.apk").Length
Write-Host "Size: $($size / 1KB) KB"
