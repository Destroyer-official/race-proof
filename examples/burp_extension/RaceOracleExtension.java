package burp.raceoracle;

import burp.api.montoya.BurpExtension;
import burp.api.montoya.MontoyaApi;
import burp.api.montoya.http.message.HttpRequestResponse;
import burp.api.montoya.ui.contextmenu.ContextMenuEvent;
import burp.api.montoya.ui.contextmenu.ContextMenuItemsProvider;
import burp.api.montoya.logging.Logging;

import javax.swing.*;
import java.awt.Component;
import java.awt.Desktop;
import java.io.File;
import java.io.FileWriter;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.*;

/**
 * Race Oracle Montoya Extension for Burp Suite.
 *
 * Adds right-click verification for race conditions across Burp Suite
 * (Intruder, Repeater, Logger, Proxy). Automatically exports selected
 * request/response pairs, runs Race Oracle verification, and opens the
 * interactive visual evidence dashboard.
 */
public class RaceOracleExtension implements BurpExtension, ContextMenuItemsProvider {

    private MontoyaApi api;
    private Logging logging;

    @Override
    public void initialize(MontoyaApi api) {
        this.api = api;
        this.logging = api.logging();

        api.extension().setName("Race Oracle Concurrency Verifier");
        api.userInterface().registerContextMenuItemsProvider(this);

        logging.logToOutput("=================================================");
        logging.logToOutput(" Race Oracle Burp Extension Initialized");
        logging.logToOutput(" Right-click concurrent responses -> 'Verify with Race Oracle'");
        logging.logToOutput("=================================================");
    }

    @Override
    public List<Component> provideMenuItems(ContextMenuEvent event) {
        List<HttpRequestResponse> selected = event.selectedRequestResponses();
        if (selected == null || selected.size() < 2) {
            return Collections.emptyList();
        }

        JMenuItem menuItem = new JMenuItem("⚡ Verify Race Condition with Race Oracle (" + selected.size() + " items)");
        menuItem.addActionListener(e -> runVerificationAsync(selected));

        return Collections.singletonList(menuItem);
    }

    private void runVerificationAsync(List<HttpRequestResponse> items) {
        new Thread(() -> {
            try {
                logging.logToOutput("[Race Oracle] Exporting " + items.size() + " HTTP items to HAR...");
                File tempHar = exportToHar(items);
                File outputDir = new File(System.getProperty("java.io.tmpdir"), "race_oracle_burp_" + System.currentTimeMillis());

                logging.logToOutput("[Race Oracle] Running differential analysis...");

                // Execute race-oracle verify CLI
                List<String> cmd = Arrays.asList(
                    "race-oracle", "verify",
                    "-i", tempHar.getAbsolutePath(),
                    "-o", outputDir.getAbsolutePath(),
                    "--no-agent"
                );

                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.redirectErrorStream(true);
                Process process = pb.start();

                int exitCode = process.waitFor();
                logging.logToOutput("[Race Oracle] Analysis completed (code " + exitCode + "). Output bundle at: " + outputDir.getAbsolutePath());

                // Find diff.html and launch browser
                File[] findings = outputDir.listFiles((dir, name) -> name.startsWith("finding_"));
                if (findings != null && findings.length > 0) {
                    File diffHtml = new File(findings[0], "diff.html");
                    if (diffHtml.exists() && Desktop.isDesktopSupported()) {
                        Desktop.getDesktop().browse(diffHtml.toURI());
                        logging.logToOutput("[Race Oracle] Opened interactive evidence dashboard in browser: " + diffHtml.getAbsolutePath());
                    }
                }
            } catch (Exception ex) {
                logging.logToError("[Race Oracle] Verification error: " + ex.getMessage());
            }
        }).start();
    }

    private File exportToHar(List<HttpRequestResponse> items) throws Exception {
        File temp = File.createTempFile("race_oracle_export_", ".har");
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        sdf.setTimeZone(TimeZone.getTimeZone("UTC"));

        StringBuilder sb = new StringBuilder();
        sb.append("{\n  \"log\": {\n    \"version\": \"1.2\",\n    \"creator\": {\"name\": \"Burp Suite Race Oracle\", \"version\": \"1.0\"},\n    \"entries\": [\n");

        for (int i = 0; i < items.size(); i++) {
            HttpRequestResponse item = items.get(i);
            String url = item.request().url();
            String method = item.request().method();
            String reqBody = item.request().bodyToString();
            short statusCode = item.response() != null ? item.response().statusCode() : 200;
            String respBody = item.response() != null ? item.response().bodyToString() : "";
            long elapsed = item.timingData().isPresent() ? item.timingData().get().timeBetweenRequestSentAndEndOfResponse().toMillis() : 25L;

            sb.append("      {\n");
            sb.append("        \"startedDateTime\": \"").append(sdf.format(new Date())).append("\",\n");
            sb.append("        \"time\": ").append(elapsed).append(",\n");
            sb.append("        \"request\": {\"method\": \"").append(method).append("\", \"url\": \"").append(escapeJson(url)).append("\"},\n");
            sb.append("        \"response\": {\"status\": ").append(statusCode).append(", \"content\": {\"text\": \"").append(escapeJson(respBody)).append("\"}},\n");
            sb.append("        \"timings\": {\"send\": 1, \"wait\": ").append(Math.max(1, elapsed - 2)).append(", \"receive\": 1}\n");
            sb.append("      }").append(i < items.size() - 1 ? "," : "").append("\n");
        }

        sb.append("    ]\n  }\n}\n");

        try (FileWriter fw = new FileWriter(temp, StandardCharsets.UTF_8)) {
            fw.write(sb.toString());
        }
        return temp;
    }

    private String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\b", "\\b")
                .replace("\f", "\\f")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}

