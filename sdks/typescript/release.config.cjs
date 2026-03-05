module.exports = {
  branches: ["main"],
  tagFormat: "ts-sdk-v${version}",
  plugins: [
    [
      "@semantic-release/commit-analyzer",
      {
        preset: "conventionalcommits",
        releaseRules: [
          { breaking: true, release: "major" },
          { type: "feat", scope: "sdk-ts", release: "minor" },
          { type: "fix", scope: "sdk-ts", release: "patch" },
          { type: "perf", scope: "sdk-ts", release: "patch" },
          { type: "refactor", scope: "sdk-ts", release: "patch" },
          { type: "chore", scope: "sdk-ts", release: "patch" },
        ],
      },
    ],
    [
      "@semantic-release/release-notes-generator",
      {
        preset: "conventionalcommits",
      },
    ],
    [
      "@semantic-release/changelog",
      {
        changelogFile: "CHANGELOG.md",
      },
    ],
    [
      "@semantic-release/npm",
      {
        npmPublish: true,
      },
    ],
    "@semantic-release/github",
    [
      "@semantic-release/git",
      {
        assets: ["package.json", "CHANGELOG.md"],
        message:
          "chore(release): ts sdk v${nextRelease.version} [skip ci]\n\n${nextRelease.notes}",
      },
    ],
  ],
};
