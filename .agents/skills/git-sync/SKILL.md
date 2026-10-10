---
name: git-sync
description: >-
  Use this skill to automate the process of staging relevant files, generating a comprehensive semantic commit message, committing the code, and pushing it to the remote branch.
---

# Git Sync Workflow

When the user activates this skill or asks you to commit and push changes, follow these exact steps:

1. **Analyze Changes**: Run `git status` to see what files were modified, deleted, or added.
2. **Filter Junk Files**: Identify any temporary scratch files (e.g., `*.bak`, temporary python test scripts, or local `.txt` outputs). Do NOT stage them.
3. **Stage Relevant Files**: Use `git add <file1> <file2>...` or `git add <folder>/` to stage the actual project files. NEVER use `git add .` to avoid accidentally committing junk.
4. **Draft Commit Message**: Analyze the changes and generate a professional commit message using Conventional Commits format (e.g., `feat: ...`, `fix: ...`, `chore: ...`). If there are multiple changes, include a bulleted list in the commit body.
5. **Commit**: Run `git commit -m "<your generated message>"`.
6. **Push**: Run `git push origin HEAD` to push the current branch to the remote repository.
7. **Report**: Tell the user that the operation was successful and show them the commit message you generated.
