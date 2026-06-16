# Demo scenario (the 5-minute story)

The end-to-end scenario Cassette is built toward. Every team member should know it cold.

![Demo debug session](images/demo_debug_session.png)

**Setup:** a Jira-triage agent that reads incoming tickets, sets priority, assigns them to teams, and emails the reporter.

## Act 1: failure (30s)

Run the agent live. It assigns a ticket to the wrong team and drafts an aggressive email. The run completes with no error: a silent failure. Show the flat log. Explain why you cannot re-run it (the email would send again).

## Act 2: flight recorder (45s)

Open Cassette. Show the recorded trace in the trajectory tree. Every step visible, every tool call inspectable. Side-effecting nodes (the email send) highlighted. Show the step inspector for the email step: exact prompt, exact output.

## Act 3: temporal blame graph (60s)

Trigger root-cause analysis. The nodes color in: step 8 (the wrong assignment) is orange, step 2 (the tool response that returned an ambiguous priority) lights up red. "Step 8 is where it failed. Step 2 is why."

## Act 4: safe replay (45s)

Trigger replay. The full run re-executes. The email tool is intercepted and mocked: nothing is sent. Show the side-effect containment counter: 0. The agent reaches the same wrong conclusion, because nothing has been fixed yet, just proving we can replay safely.

## Act 5: debug agent + counterfactual fix (90s)

Type in plain English: "at step 2, priority should have been high, not medium." The debug agent builds the JSON injection. Replay fires from step 2. The counterfactual agent generates 4 more variants automatically. All run in parallel. Show the ranking: Variant 3 wins, an explicit priority-enum constraint resolved the failure. Zero side effects throughout.

## Act 6: verified fix (30s)

Update the agent's system-prompt config with the winning variant. Show the updated config. The next production run will use the fixed prompt. The whole loop (detect, locate, fix, verify) completed without touching production once.
