const core = require("@actions/core");
const github = require("@actions/github");

const POLL_INTERVAL_MS = 10000;
const MAX_POLL_ATTEMPTS = 120; // 20 minutes max

async function run() {
  try {
    const apiKey = core.getInput("api-key", { required: true });
    const apiUrl = core.getInput("api-url");
    const failBelow = parseInt(core.getInput("fail-on-health-below") || "0", 10);
    const commentOnPr = core.getInput("comment-on-pr") === "true";

    // Default to current repo if not specified
    let repoUrl = core.getInput("repo-url");
    if (!repoUrl) {
      const { owner, repo } = github.context.repo;
      repoUrl = `https://github.com/${owner}/${repo}`;
    }

    core.info(`Analyzing: ${repoUrl}`);
    core.info(`API URL: ${apiUrl}`);

    // Start analysis
    const startResp = await fetch(`${apiUrl}/api/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify({ repo_url: repoUrl, force: false }),
    });

    if (!startResp.ok) {
      const err = await startResp.text();
      throw new Error(`Failed to start analysis: ${startResp.status} ${err}`);
    }

    const analysis = await startResp.json();
    const analysisId = analysis.id;
    core.info(`Analysis started: ${analysisId}`);

    // Poll for completion
    let result = null;
    for (let i = 0; i < MAX_POLL_ATTEMPTS; i++) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

      const pollResp = await fetch(`${apiUrl}/api/analysis/${analysisId}`, {
        headers: { "X-API-Key": apiKey },
      });

      if (!pollResp.ok) continue;

      const data = await pollResp.json();
      core.info(`Status: ${data.status} — ${data.stage || ""}`);

      if (data.status === "completed") {
        result = data;
        break;
      }
      if (data.status === "failed") {
        throw new Error(`Analysis failed: ${data.error_message || "Unknown error"}`);
      }
    }

    if (!result) {
      throw new Error("Analysis timed out after 20 minutes");
    }

    // Extract health score
    const healthScore = result.health_score?.overall_score || 0;
    const healthGrade = result.health_score?.grade || "?";

    core.setOutput("analysis-id", analysisId);
    core.setOutput("health-score", healthScore.toString());
    core.setOutput("health-grade", healthGrade);

    core.info(`Health: ${healthGrade} (${healthScore}/100)`);

    // Post PR comment
    if (commentOnPr && github.context.payload.pull_request) {
      const token = process.env.GITHUB_TOKEN;
      if (token) {
        const octokit = github.getOctokit(token);
        const { owner, repo } = github.context.repo;
        const prNumber = github.context.payload.pull_request.number;

        const arch = result.result?.architecture || {};
        const dimensions = result.health_score?.dimensions || {};
        const dimLines = Object.entries(dimensions)
          .map(([k, v]) => `| ${v.label || k} | ${v.score}/100 |`)
          .join("\n");

        const appUrl = apiUrl.includes("railway")
          ? "https://www.hootlylabs.com"
          : "http://localhost:3000";

        const body = [
          `## Hootly Analysis`,
          ``,
          `**Health Score: ${healthGrade} (${healthScore}/100)**`,
          ``,
          `| Dimension | Score |`,
          `|-----------|-------|`,
          dimLines,
          ``,
          `**Stack:** ${(arch.tech_stack || []).join(", ")}`,
          `**Type:** ${arch.architecture_type || "Unknown"}`,
          ``,
          `[View full analysis](${appUrl}/analysis/${analysisId})`,
        ].join("\n");

        await octokit.rest.issues.createComment({
          owner,
          repo,
          issue_number: prNumber,
          body,
        });

        core.info("PR comment posted");
      }
    }

    // Fail if below threshold
    if (failBelow > 0 && healthScore < failBelow) {
      core.setFailed(
        `Health score ${healthScore} is below threshold ${failBelow}`
      );
    }
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
