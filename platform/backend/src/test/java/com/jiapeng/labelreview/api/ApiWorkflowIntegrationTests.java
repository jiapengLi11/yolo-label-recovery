package com.jiapeng.labelreview.api;

import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.domain.UserRole;
import com.jiapeng.labelreview.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Path;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ApiWorkflowIntegrationTests {

    private static final Pattern STRING_VALUE = Pattern.compile("\\\"%s\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"");
    private static final Pattern NUMBER_VALUE = Pattern.compile("\\\"%s\\\"\\s*:\\s*(\\d+)");

    @Autowired
    private ServletWebServerApplicationContext server;

    @Autowired
    private UserRepository users;

    @Autowired
    private PasswordEncoder encoder;

    @TempDir
    Path reviewRoot;

    private HttpClient client;
    private String adminUsername;
    private String reviewerUsername;

    @BeforeEach
    void setUp() {
        client = HttpClient.newHttpClient();
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        adminUsername = "api-admin-" + suffix;
        reviewerUsername = "api-reviewer-" + suffix;
        users.save(new AppUser(adminUsername, encoder.encode("IntegrationPass123!"), "API Admin", UserRole.ADMIN));
    }

    @Test
    void completeAdminAndReviewerWorkflowOverHttp() throws Exception {
        String adminToken = login(adminUsername, "IntegrationPass123!");
        HttpResponse<String> project = post(
                "/api/projects",
                adminToken,
                "{\"name\":\"API workflow\",\"description\":\"integration\",\"reviewRoot\":\""
                        + escape(reviewRoot.toString()) + "\"}");
        assertThat(project.statusCode()).isEqualTo(200);
        long projectId = number(project.body(), "id");

        HttpResponse<String> unassignedUser = post(
                "/api/admin/users",
                adminToken,
                "{\"username\":\"unassigned-" + reviewerUsername
                        + "\",\"password\":\"ReviewerPass123!\",\"displayName\":\"Unassigned\","
                        + "\"role\":\"REVIEWER\",\"projectIds\":[]}");
        assertThat(unassignedUser.statusCode()).isEqualTo(400);

        HttpResponse<String> user = post(
                "/api/admin/users",
                adminToken,
                "{\"username\":\"" + reviewerUsername
                        + "\",\"password\":\"ReviewerPass123!\",\"displayName\":\"Reviewer\","
                        + "\"role\":\"REVIEWER\",\"projectIds\":[" + projectId + "]}");
        assertThat(user.statusCode()).isEqualTo(200);
        assertThat(post(
                        "/api/projects/" + projectId + "/tasks:batch",
                        adminToken,
                        "[{\"candidateId\":\"R-API-1\",\"split\":\"train\",\"imageName\":\"sample.jpg\","
                                + "\"className\":\"helmet\",\"confidence\":0.92,\"caseCode\":\"GT0_AUTO1\","
                                + "\"recommendedAction\":\"accept_add_or_reject\",\"visualFile\":\"visuals/sample-1.jpg\"},"
                                + "{\"candidateId\":\"R-API-2\",\"split\":\"train\",\"imageName\":\"sample.jpg\","
                                + "\"className\":\"vest\",\"confidence\":0.81,\"caseCode\":\"GT0_AUTO1\","
                                + "\"recommendedAction\":\"accept_add_or_reject\",\"visualFile\":\"visuals/sample-2.jpg\"}]").statusCode())
                .isEqualTo(200);

        String reviewerToken = login(reviewerUsername, "ReviewerPass123!");
        HttpResponse<String> claimed = post(
                "/api/tasks/claim-next?projectId=" + projectId,
                reviewerToken,
                null);
        assertThat(claimed.statusCode()).isEqualTo(200);
        long taskId = number(claimed.body(), "id");
        long version = number(claimed.body(), "version");

        HttpResponse<String> imageCandidates = get(
                "/api/tasks/" + taskId + "/image-candidates",
                reviewerToken);
        assertThat(imageCandidates.statusCode()).isEqualTo(200);
        assertThat(imageCandidates.body()).contains("R-API-1").contains("R-API-2");
        Matcher candidateIds = Pattern.compile("\\\"id\\\"\\s*:\\s*(\\d+)").matcher(imageCandidates.body());
        long siblingTaskId = -1;
        while (candidateIds.find()) {
            long id = Long.parseLong(candidateIds.group(1));
            if (id != taskId) siblingTaskId = id;
        }
        assertThat(siblingTaskId).isPositive();

        HttpResponse<String> decision = post(
                "/api/tasks/" + taskId + "/decision",
                reviewerToken,
                "{\"decision\":\"ACCEPT_ADD\",\"expectedVersion\":" + version + ",\"comment\":\"verified\"}");
        assertThat(decision.statusCode()).isEqualTo(200);
        assertThat(decision.body()).contains("\"state\":\"COMPLETED\"");

        long completedVersion = number(decision.body(), "version");
        HttpResponse<String> revised = put(
                "/api/tasks/" + taskId + "/decision",
                reviewerToken,
                "{\"decision\":\"REJECT\",\"expectedVersion\":" + completedVersion + ",\"comment\":\"corrected\"}");
        assertThat(revised.statusCode()).isEqualTo(200);
        assertThat(get("/api/tasks/" + taskId + "/image-candidates", reviewerToken).body())
                .contains("\"decision\":\"REJECT\"")
                .contains("\"decisionComment\":\"corrected\"");

        HttpResponse<String> siblingClaim = post(
                "/api/tasks/" + siblingTaskId + "/claim",
                reviewerToken,
                null);
        assertThat(siblingClaim.statusCode()).isEqualTo(200);
        long siblingVersion = number(siblingClaim.body(), "version");
        assertThat(post(
                        "/api/tasks/" + siblingTaskId + "/decision",
                        reviewerToken,
                        "{\"decision\":\"ACCEPT_ADD\",\"expectedVersion\":" + siblingVersion + ",\"comment\":\"second box\"}")
                .statusCode()).isEqualTo(200);

        HttpResponse<String> recent = get(
                "/api/tasks/recent?projectId=" + projectId + "&limit=10",
                reviewerToken);
        assertThat(recent.statusCode()).isEqualTo(200);
        assertThat(recent.body())
                .contains("R-API-1")
                .contains("R-API-2")
                .contains("corrected")
                .contains("second box");

        HttpResponse<String> progress = get("/api/projects/" + projectId + "/progress", reviewerToken);
        assertThat(progress.statusCode()).isEqualTo(200);
        assertThat(progress.body()).contains("\"completed\":2").contains("\"completionRate\":1.0");
    }

    @Test
    void importsHistoricalDecisionsIdempotently() throws Exception {
        String adminToken = login(adminUsername, "IntegrationPass123!");
        HttpResponse<String> project = post(
                "/api/projects",
                adminToken,
                "{\"name\":\"History import\",\"description\":\"migration\",\"reviewRoot\":\""
                        + escape(reviewRoot.toString()) + "\"}");
        long projectId = number(project.body(), "id");

        String tasks = "["
                + "{\"candidateId\":\"R-HISTORY-1\",\"split\":\"train\",\"imageName\":\"one.jpg\","
                + "\"className\":\"helmet\",\"confidence\":0.92,\"caseCode\":\"GT0_AUTO1\","
                + "\"recommendedAction\":\"accept_add_or_reject\",\"visualFile\":\"visuals/one.jpg\"},"
                + "{\"candidateId\":\"R-HISTORY-2\",\"split\":\"train\",\"imageName\":\"two.jpg\","
                + "\"className\":\"person\",\"confidence\":0.75,\"caseCode\":\"GT1_AUTO1\","
                + "\"recommendedAction\":\"replace_or_reject\",\"visualFile\":\"visuals/two.jpg\"}"
                + "]";
        assertThat(post("/api/projects/" + projectId + "/tasks:batch", adminToken, tasks).statusCode())
                .isEqualTo(200);

        String history = "["
                + "{\"candidateId\":\"R-HISTORY-1\",\"decision\":\"ACCEPT_ADD\",\"comment\":\"legacy\"},"
                + "{\"candidateId\":\"R-HISTORY-2\",\"decision\":\"UNCERTAIN\",\"comment\":\"legacy\"},"
                + "{\"candidateId\":\"R-UNKNOWN\",\"decision\":\"REJECT\",\"comment\":\"legacy\"}"
                + "]";
        HttpResponse<String> first = post(
                "/api/projects/" + projectId + "/decisions:history",
                adminToken,
                history);
        assertThat(first.statusCode()).isEqualTo(200);
        assertThat(first.body()).contains("\"imported\":2").contains("\"unknownCandidates\":1");

        HttpResponse<String> second = post(
                "/api/projects/" + projectId + "/decisions:history",
                adminToken,
                history);
        assertThat(second.statusCode()).isEqualTo(200);
        assertThat(second.body()).contains("\"imported\":0").contains("\"skippedExisting\":2");

        HttpResponse<String> progress = get("/api/projects/" + projectId + "/progress", adminToken);
        assertThat(progress.body())
                .contains("\"completed\":1")
                .contains("\"escalated\":1")
                .contains("\"completionRate\":1.0");
    }

    private String login(String username, String password) throws Exception {
        HttpResponse<String> response = post(
                "/api/auth/login",
                null,
                "{\"username\":\"" + username + "\",\"password\":\"" + password + "\"}");
        assertThat(response.statusCode()).isEqualTo(200);
        return string(response.body(), "accessToken");
    }

    private HttpResponse<String> post(String path, String token, String json) throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder(uri(path))
                .header("Content-Type", "application/json")
                .POST(json == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(json));
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        return client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> get(String path, String token) throws Exception {
        return client.send(
                HttpRequest.newBuilder(uri(path))
                        .header("Authorization", "Bearer " + token)
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> put(String path, String token, String json) throws Exception {
        return client.send(
                HttpRequest.newBuilder(uri(path))
                        .header("Content-Type", "application/json")
                        .header("Authorization", "Bearer " + token)
                        .PUT(HttpRequest.BodyPublishers.ofString(json))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private URI uri(String path) {
        return URI.create("http://127.0.0.1:" + server.getWebServer().getPort() + path);
    }

    private static String string(String json, String field) {
        Matcher matcher = Pattern.compile(STRING_VALUE.pattern().formatted(Pattern.quote(field))).matcher(json);
        if (!matcher.find()) {
            throw new AssertionError("Missing JSON field " + field + ": " + json);
        }
        return matcher.group(1);
    }

    private static long number(String json, String field) {
        Matcher matcher = Pattern.compile(NUMBER_VALUE.pattern().formatted(Pattern.quote(field))).matcher(json);
        if (!matcher.find()) {
            throw new AssertionError("Missing JSON field " + field + ": " + json);
        }
        return Long.parseLong(matcher.group(1));
    }

    private static String escape(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
