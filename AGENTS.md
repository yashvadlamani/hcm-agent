# User preferences: conserve usage

- Run at most five high-priority individual test cases per change/task. Select tests that directly cover the changed behavior, its main failure path, and the most relevant regression.
- Do not run the full suite or broad test files by default. Parameterized cases count individually toward the five-test limit. Avoid repeated runs unless a code change or failure justifies them.
- If more testing is necessary, explain why and ask before exceeding five cases.
- Do not run paid live-model/API tests unless the user explicitly requests them. Prefer mocks and local checks.
- Keep responses, tool output, file inspection, and tool calls concise and focused. Avoid redundant searches and checks.
- Report what was tested and any remaining uncertainty without implying that untested behavior was verified.

These preferences persist for this project unless the user explicitly overrides them.
