# eFlow workflow knowledge
Version: 2026-10-23
Reviewed against current application source. Guidance describes workflows, not hosted deployment promises or current financial balances.

Maintainer format: each level-two heading contains a stable topic ID, display title and role allowlist. Keywords, Intents and Sources are retrieval/audit metadata, not spoken answers. Optional Intents lists semicolon-separated action phrases: all normalized words in a phrase must occur in the question; the most specific matching phrases narrow retrieval to their workflows. Keep each answer paragraph complete and below 1,000 characters. Bump Version when changing workflow rules. Paths refer to EflowWeb unless the path names an AI-server module. Do not describe a pending migration as verified hosted behavior.

## overview | What eFlow does and what the assistant can explain | head,member,accounting_staff,admin
Keywords: capabilities introduction help getting started system assistant navigation
Sources: src/app/features/navigation; src/app/features/help-assistant
- eFlow organizes office projects, tasks, people, schedules, reviews and the associated budget and cash workflow. Start in My Work for assignments, Workspaces for office/project work, or Inbox for available decisions and updates.
- The assistant explains workflows and can discuss visible task blockers when you select a project. It is read only: it cannot assign people, approve work, send invitations, release money or change records for you.
- Answers use this workflow guide and records available to your account. AI can be wrong; verify important decisions in the relevant eFlow screen.

## navigation | Find pages, projects and views | head,member,accounting_staff
Keywords: where sidebar home overview dashboard favorites favourites search all projects
Sources: src/app/features/navigation; src/app/features/projects
- Open Workspaces, then All projects, to search projects available to your account. Use the sidebar project name or Open project to enter its workspace. Favorites gives quick access to starred projects.
- Main table is the detailed project work list. Board, Gantt, Calendar, Project Dashboard and Offices show other views of the same project; changing views does not create duplicate tasks.
- Workspace Overview summarizes office work. My Work is personal, while Inbox contains relevant requests and updates. A missing destination can reflect role or access rather than an empty project.

## projects | Projects and project setup | head,member,accounting_staff
Keywords: create new project planning lead office project lead setup activation activate readiness
Sources: src/app/features/projects; src/app/features/project-readiness/components/SetupReadinessChecks.tsx
- Use All projects and Create project, or the available New action, to create a project. Review its name, responsible office, project lead and dates, then add people and delivery tasks.
- For a planning project, the appointed Head opens Setup & activation. Review work plan, schedule and budget checks, then resolve the displayed task, office and staffing blockers before confirming activation.
- Setup is a closable modal with confirmed checks separated from remaining actions. Active projects do not need a redundant activation button; later material changes can still require current review.

## columns | Use every Main table column | head,member,accounting_staff
Keywords: columns table owner status priority budget estimated hours dependencies timeline add column filters
Sources: src/app/features/project-table/components/ProjectTaskCells.tsx; src/app/features/project-table/columnLayout.ts
- Columns or Add column controls optional fields such as Office, estimated hours, dependencies and Budget. Search and filters affect what is shown; they do not delete saved work.
- Owner identifies lead and contributors. Status records the work state, dates schedule it, priority expresses urgency, and estimated hours describes planned effort. A date or priority alone is not approval or completion.
- Dependencies link prerequisite work. Budget opens the task's actual funding allocation; an amount shown as from plan is planning information rather than authorized funding.

## groups | Task groups and deleting a group | head,member,accounting_staff
Keywords: group default empty to do delete group remove collapse expand
Sources: src/app/features/project-table/groupDeletion.ts; src/app/features/project-table/hooks/useGroupDeletion.tsx
- Groups organize project rows. Use New group, the group menu and disclosure arrow to add, manage, collapse or expand them.
- An empty default group is not mandatory. Import can remove empty defaults while retaining defaults that contain work. Deleting a group must not bypass active-task or financial-history protections.
- Before deleting a populated group, inspect the confirmation and affected tasks. Started, reviewed, archived or financially linked work can need a different permitted action; the displayed server blocker is authoritative.

## tasks | Task status, leads and execution | head,member,accounting_staff
Keywords: task status progress not started in progress stuck changes requested for review completed
Sources: src/app/features/tasks; src/app/features/nested-work; src/app/features/work-state
- Open a task in Main table or My Work to inspect its lead, contributors, office, dates, required result, evidence and dependencies before starting.
- In progress means work is being carried out. Stuck or changes requested calls for a blocker or feedback check. For review means it awaits the configured reviewer, not that it is already completed.
- Progress and status follow permitted execution/review actions. Updating a percentage, attaching a file or setting a date does not bypass submission, financial clearance or completion requirements.

## subtasks | Subtasks, subitems and parent completion | head,member,accounting_staff
Keywords: subtask subitem child hierarchy evidence parent task approval review
Sources: src/app/features/nested-work; src/app/features/subtasks
- Expand the task disclosure arrow to see subitems, or open task details to inspect the hierarchy. Add subitem or child work requires current branch-management permission.
- A subtask assignee records progress and submits the required completion note and evidence to the assigned reviewer. Finishing execution is different from receiving approval.
- Parent completion can wait for child approvals, dependencies or financial clearance. Open the blocked child item and resolve its next action instead of changing the parent status as a shortcut.

## reviews | Evidence, submission and requesting changes | head,member,accounting_staff
Keywords: submit evidence completion note attachments reviewer approve review resubmit changes requested
Sources: src/app/features/tasks; src/app/features/nested-work; src/app/features/authentication/workflow-preview/workflowGuides.ts
- Before Submit for review, check completion requirements, add the required completion note and supporting evidence, and resolve prerequisite or cash-clearance blockers.
- The authorized reviewer examines results and evidence, then approves or requests changes through the review action. Ownership, project membership and review authority are separate.
- When changes are requested, read the feedback, correct work and evidence, then resubmit. A previous submission or AI statement does not approve the revised work.

## dependencies | Dependencies and prerequisite blockers | head,member,accounting_staff
Keywords: dependency prerequisite blocked sequence cannot start parent waiting
Sources: src/app/features/project-table/components/DependencyCell.tsx; src/app/features/nested-work
- Open Dependencies or task details to see prerequisite work. A dependency is a saved work relationship, not simply an earlier date on the calendar.
- If a prerequisite is unfinished, open it, inspect the assignee and review state, and resolve its permitted next action. Do not delete dependency links just to bypass approval requirements.
- The assistant can only explain dependencies visible to your account. An unavailable prerequisite may need the authorized project or office manager to inspect it.

## schedule | Project dates, due dates and schedule views | head,member,accounting_staff
Keywords: dates schedule due deadline gantt calendar timeline overdue manual order sort
Sources: src/app/features/project-readiness; src/app/features/project-table; src/app/shared/calendarDisplay.ts
- Set project start and end dates through the available project-dates or timeline action. Review task timelines separately; valid project dates do not automatically set every task deadline.
- Use Gantt for time relationships and Calendar for dated work. Check the saved date, dependency and status before moving work or interpreting an overdue badge.
- Displayed dates follow application calendar rules, including Manila financial dates. Changing a task date does not settle its cash or approve its work.

## stalled | Why a project is stalled and who needs follow-up | head,member,accounting_staff
Keywords: stalled stuck overdue delayed waiting blocker who has not done job unfinished responsible
Sources: server/help_assistant/context.py; src/app/features/project-readiness
- A project may wait on unassigned tasks, unfinished prerequisites, requested changes, missing evidence, pending review, financial clearance or required office participation.
- Inspect the task's next action first. For review usually needs the authorized reviewer; unassigned work needs staffing; requested changes need the recorded feedback addressed.
- An overdue date or named lead identifies a recorded follow-up, not proof of poor effort. Missing updates and restricted records can hide important context.
- Select the project in Help before asking which tasks need follow-up. The assistant reads visible unarchived work and recorded blockers, not private HR data or employee effort.

## budget | Does setting a task Budget consume Office Budget? | head,member,accounting_staff
Intents: planning estimate; budget estimate; budget reserve
Keywords: budget budjet task amount estimate from plan reserve deduct eat money committed allocation authorize
Sources: src/app/features/budget/components/ProjectTaskBudget.tsx; src/app/features/budget/components/DirectWorkFunding.tsx
- Click Budget or Set budget for the task in Main table. The appointed Head of the responsible office needs a saved, locked annual Office Budget before authorizing funding.
- Select real annual accounts, enter approved amounts and the reason or authority reference, then confirm Authorize work funding. Successful authorization reserves that amount from Office Budget once and creates approved task funding.
- Authorized task funding is already reserved. Petty-cash requests or releases against it do not reserve the annual amount again. Funding changes remain in Office Budget to keep requests, receipts and audit history reconciled.
- A PDF or draft amount, including a number labelled from plan, is not funding authorization. Check the approved allocation and ledger; typing a planning estimate alone does not charge Office Budget.

## annual_budget | Configure annual Office Budget and fiscal year | head,member,accounting_staff
Intents: annual budget; fiscal budget
Keywords: annual appropriation section account partition fiscal year lock save budget setup annual authority
Sources: src/app/features/budget/components/AnnualBudgetSetup.tsx; src/app/features/budget/services/budgetSectionService.ts
- Open Office Budget for the correct office and fiscal year. Build annual sections/accounts, review totals and cash limits, save the draft, then use the authorized lock action before funding work.
- Annual setup includes daily petty-cash release limits, per-receipt limits, liquidation due days and permitted override settings. Saved limits constrain later cash actions; they are not decorative fields.
- Locked or closed years have stricter editing rules. Use the permitted adjustment action and reason where available, rather than replacing a budget to hide a commitment or bypass a year guard.

## budget_position | Available budget, commitments and cash returns | head,member,accounting_staff
Keywords: remaining balance spent available appropriation commitment outstanding advance returned cash double counting
Sources: src/app/features/budget/components/BudgetPositionSummary.tsx; src/app/features/budget/selectors/financialPosition.ts
- Office Budget separates annual authority, commitments, cash released, unsettled advances, actual spending and returned cash. These are stages of the same funding, not separate amounts to add together as expenditure.
- For example, 10,000 pesos of available annual authority with 3,000 committed leaves 7,000 for new commitments. Settling a 500-peso advance as 400 spent and 100 returned does not release the unused commitment.
- Returned cash clears an advance; it does not decommit project funding. Check authoritative remaining appropriation and allocation balances instead of calculating availability from spending alone.

## cash | Request petty cash from a funded task | head,member,accounting_staff
Intents: request cash
Keywords: petty cash request amount purpose recipient funded task financial actions advance
Sources: src/app/features/budget; src/app/features/nested-work; src/app/features/authentication/workflow-preview/workflowGuides.ts
- Open the eligible task's financial or Funding actions and choose Request petty cash. Provide the purpose, amount, recipient and required supporting information. The request uses current authorized task funding.
- The server checks the remaining task pool and applicable office, fiscal-year, recipient and cash limits. Membership alone does not grant request, approval, release or settlement permission.
- A submitted request waits for its required decision and release scheduling. A request, reservation or approval message is not proof that cash was already released.

## cash_rejection | Reject, correct and re-request petty cash | head,member,accounting_staff
Intents: reject cash; reject request cash; resubmit cash; resubmit request cash
Keywords: cash rejected rejection resubmit returned revise re request resubmission decline cancel delete
Sources: src/app/features/budget/services/budgetService.ts; supabase/migrations/20260824000008_budget_controls_and_resubmission.sql
- If cash is rejected or returned, open the recorded feedback, correct the purpose, amount or supporting information, then use the available revision or resubmission action.
- Rejection does not authorize release. Check the saved request state and pool before requesting again; a duplicate request is not the same as correcting a rejected one.
- Cancel or delete only in permitted states. Released advances, settlements and audit records follow the financial workflow rather than being erased to start again.

## cash_release | Voucher and cash release schedules | head,member,accounting_staff
Keywords: voucher cash releases accounting tranche cheque check release daily limit scheduled future due override
Sources: src/app/features/budget/components/DisbursementVoucherDialog.tsx; src/app/features/budget/components/CashReleaseOverrideDialog.tsx
- Authorized Accounting staff use Voucher & Cash Releases to inspect approved requests, voucher details and scheduled tranches. Verify recipient, remaining amount and permitted release date before confirming.
- Releases are checked against current authority, calendar, daily and request limits. A future scheduled tranche is not already cash in the recipient's hands.
- An available schedule override requires the permitted actor, selected tranche and audited reason. It changes release timing, not unrelated approval or posting authority.

## settlement | Liquidation, receipts and unused cash | head,member,accounting_staff
Intents: settlement; liquidation
Keywords: liquidation settlement receipt actual expense unused money cash returned late overdue advance
Sources: src/app/features/budget/components/AccountingSettlementQueue.tsx
- After using released cash, submit liquidation or settlement with actual expenses, required receipts and returned unused cash. Explain discrepancies and provide supporting details.
- The authorized reviewer checks the current package. Accounting settlement/posting is separate from merely uploading receipts; an outstanding advance is not verified actual spending.
- If receipt limits, lateness, missing documents or unresolved amounts block settlement, follow the displayed authorized correction or escalation. Do not invent approval or overwrite a posted entry.

## independent_review | Conflicted Accounting review and independent leadership | head,member,accounting_staff
Intents: independent review; conflicted accounting; conflict accounting
Keywords: conflict accounting officer own request recipient lead independent head assistant review settle post journal
Sources: src/app/features/budget/services/independentReviewService.ts; src/app/features/budget/components/AssignedIndependentReviews.tsx
- Accounting involvement as requester, recipient or relevant task lead can require the named independent leadership review shown for the current package.
- An eligible appointed Head or Assistant can review the assigned package, including from Inbox where provided. That review does not grant general Accounting browsing, settlement or journal-posting permission.
- An authorized independent Accounting Officer settles/posts after required review. If no eligible reviewer or poster exists, escalate; do not self-approve or promote another user as a shortcut.

## journal | General Journal and financial audit history | head,member,accounting_staff
Keywords: general journal debit credit posting memo account balance immutable audit trail correction
Sources: src/app/features/budget/components/JournalEntryPage.tsx; src/app/features/budget/components/journalEntry.css
- Authorized Accounting users open General Journal, choose office and fiscal year, and open an entry to inspect posting metadata, memo, all accounts, debit/credit totals and record references.
- Posted entries are financial history. Changing a task, deleting a request or asking AI to correct an entry does not edit that history; use an authorized balanced correction where available.
- Full entries can include lines outside the workspace filter. Read both debit and credit and the complete totals before concluding an entry is unbalanced.

## people | Project members versus task assignment | head,member,accounting_staff
Keywords: add people project team selected checkboxes membership lead contributor choose people roles
Sources: src/app/features/projects; src/app/features/tasks; src/app/features/staffing
- Add people manages project team access. A checked project member is not automatically the lead of every task; task lead and contributors are saved separately.
- Use Choose people on a task to inspect lead and contributors, then save the permitted team change. A contributor helps deliver work without automatically becoming its reviewer or manager.
- Project participation does not create permanent office membership or promote an employee to a permanent system Head.

## auto_assignment | Small AI auto-assign, eligible people and LAYA | head,member,accounting_staff
Keywords: ai auto assign automatically choose team qwen laya skills workload membership available candidates
Sources: src/app/features/staffing/services/autoAssignment.ts; src/app/features/staffing/components/AutoAssignTaskButton.tsx; server/workspace_staffing.py
- Use AI auto-assign for eligible unassigned work. The small task assignment path proposes lead/contributors using Qwen3.5:4b, LAYA review and validation before saving the team.
- Eligible people can be enrolled in the project during an authorized assignment; AI is not limited to names already checked in Add people. It cannot pick arbitrary accounts outside the confirmed staffing rules or invent staff.
- Check saved lead, contributors and project membership. When an office has nobody eligible or available, resolve Needs people by adding or inviting the appropriate participant rather than assuming AI assigned someone.

## offices | Lead and participating offices | head,member,accounting_staff
Keywords: offices office tab lead participating observer responsibility blank check office name needs people contact
Sources: src/app/features/project-offices; src/app/features/project-import/services/pdfOffices.ts
- In Offices, inspect the lead office, other relationships, participation status and selected members. Adding an office entry is different from an invited person accepting project access.
- An imported office can have no contact or joined members. Check office name or Needs people calls for manual identity review and staffing; import does not silently send invitations.
- A budget funder is not automatically a participating office. Relevant LGU Offices is a broad label to clarify, not a literal office name to create.

## invitations | Project invitations and permanent office membership | head,member,accounting_staff
Keywords: invite representative head employee temporary guest project access pending sent joined accepted email
Sources: src/app/features/project-offices; src/app/features/invitations; server/routers/invitations.py
- For project invitations, choose the appropriate relationship, such as office representative or office employee, and inspect sent, pending or joined status. Sending an invitation remains a manual authorized action.
- Another office's Head is not always required for an invited employee to participate directly. The project relationship controls project scope and must not permanently promote the participant to system Head.
- Office Team handles permanent office members/invitations; project participation is project-specific. Check which invitation screen you are using before assuming permanent office access.

## pdf | Import a proposal PDF into an existing project | head,member,accounting_staff
Keywords: import pdf document groups tasks budgets office extraction checkbox batch retry resume source count
Sources: src/app/features/project-import; src/app/features/project-table
- The Head can use Import PDF beside Add people. Choose the schedule start and whether to add extracted offices, select the PDF, and follow the processing modal while it builds the project table.
- Review extracted groups, task count, schedules, priorities, budget planning amounts, staffing and source totals. Source funding labels do not themselves authorize Office Budget commitments.
- The office checkbox controls adding extracted office entries; they can still need identity and people checks. Use a failed import's saved batch retry/resume instead of starting duplicate imports.

## proposals | Saved work plans and proposal drafts | head,member,accounting_staff
Keywords: saved work plans proposal review draft proposal create work plan
Sources: src/app/features/authentication/workflow-preview/workflowGuides.ts
- Work plan drafts hold proposed structure, offices, tasks, people, schedules and budgets before operational publication. Correct and save the draft before asking offices to approve it.
- Within-office and interdepartmental plans have different participation checks. An office-only proposal does not require another office merely to satisfy a generic collaboration step.
- Creating/importing a saved draft is not publishing operational work or reserving approved annual funding.

## participation | Office participation approvals and proposal changes | head,member,accounting_staff
Keywords: proposal participation approval review governance office decline request updates resend revision
Sources: src/app/features/authentication/workflow-preview/workflowGuides.ts
- For plans requiring other offices, the lead sends participation requests for the saved current plan. Each required office examines responsibilities, staffing and scope before deciding.
- When updates are requested, correct and save the plan, then resend required approvals. A previous approval may not cover material changes to the revised plan.
- Participation approval does not automatically publish a proposal, complete tasks or authorize cash. Inspect publication and financial checks separately.

## publication | Publish a proposal and reserve approved budgets | head,member,accounting_staff
Intents: publish budget; publish draft
Keywords: publish publication approved plan operational allocations commitment draft not consume funds
Sources: src/app/features/authentication/workflow-preview/workflowGuides.ts; src/app/features/budget/components/BudgetFundingHierarchy.tsx
- After required plan, participation and budget checks pass, the owning/lead office confirms publication. Publication creates operational projects, tasks and member assignments for that saved plan.
- Drafts do not consume funds. Publishing a funded proposal reserves its approved task budgets once and creates operational allocations shown in Office Budget.
- Direct funding of manual/imported project tasks instead uses Set budget and Authorize work funding. In either path, check approved allocations rather than counting a planning amount as cash spent.

## completion | Complete a project and resolve blockers | head,member,accounting_staff
Keywords: completion requirements mark project complete done all tasks financial governance blocker
Sources: src/app/features/projects/components/ProjectCompleteDialog.tsx; src/app/features/projects/components/CompletionBlockersList.tsx
- Open Completion requirements or Mark project complete to inspect unfinished work, required reviews, evidence, financial clearance and governance checks.
- Finish/review required work, resolve displayed financial blockers and obtain current required decisions before confirming completion. A dashboard percentage alone does not complete a project.
- Project completion is a separate confirmed action. Open and resolve the exact task, financial record or office check listed by a blocker.

## archive | Archive a project and retain unused funding | head,member,accounting_staff
Keywords: archive archived unused commitment retained funding return cash release decommit history
Sources: src/app/features/budget/components/BudgetPositionSummary.tsx; src/app/features/authentication/workflow-preview/workflowGuides.ts
- Use the available Archive action for eligible completed work and provide the reason. Archived records remain for reference and audit; archive is not permanent deletion.
- Archiving retains funding commitments, including unused funding. Returned cash clears advances but does not automatically release committed annual authority.
- Inspect permitted audited actions in Office Budget for funding changes. Do not assume restoring, deleting or archiving a project decommits its money.

## reopening | Reopen work and dependent reviews | head,member,accounting_staff
Keywords: reopen reopening completed prerequisite downstream approved submitted dependency delete
Sources: supabase/migrations/20261021172003_financial_independent_review_and_dependency_lifecycle.sql; src/app/features/nested-work
- A completed prerequisite cannot simply lose completion or be deleted while live dependent work is submitted/completed under the dependent-work guard.
- Inspect the dependent task and its review state. Reopen or correct dependent work through its authorized workflow first, then retry the permitted prerequisite action.
- Reopening does not authorize erasing reviewed submissions, posted journals or financial evidence. Retain history and use current review decisions for revised work.

## deletion | Permanently delete projects or tasks | head,member,accounting_staff
Keywords: delete project permanently confirmation reason current work access required deleted history links
Sources: src/app/features/projects; src/app/features/project-table/hooks/useProjectTaskDeletion.tsx
- Open the project/task More actions menu and inspect the deletion confirmation. Permanent project deletion requires the displayed reason and typed name where requested.
- The server checks current operational access and linked work. A Head label alone does not prove the required current office appointment and project permission.
- Deleting a project does not erase existing task or financial audit history. Read which records/links the confirmation affects; use archive when retained reference is intended.

## inbox | Inbox, needs action and notifications | head,member,accounting_staff
Keywords: inbox notification needs action updates follow up pending approval decision bell
Sources: src/app/features/notifications/navigation.ts; src/app/features/action-center; src/app/features/navigation/sidebarContent.tsx
- Open Inbox or the notification bell for updates and items needing action. Follow the linked task, project or financial package and inspect its current status before deciding.
- A notification is a pointer, not the current permission or decision. Its destination can show an item was already resolved, changed or is no longer accessible.
- Assigned independent financial reviews can appear in Inbox for an eligible appointed reviewer. That assignment does not grant general settlement or journal-posting authority.

## team_supervision | Office Team, Team Supervision and Team Intelligence | head,member,accounting_staff
Keywords: office team supervision intelligence workload skills staff permanent members invitations search roles
Sources: src/app/features/navigation; src/app/features/staffing
- Office Team lists permanent account members and office invitations. Search and role/status filters help distinguish active members from pending invitations.
- Team Supervision and Team Intelligence support authorized inspection of people, assignments, skills and workload. Check current work and recorded availability before assigning more tasks.
- Add people is a separate project list. An Office Team member may still need authorized project enrollment before being selected for that project's work.

## access | Roles, office appointments and access problems | head,member,accounting_staff,admin
Keywords: permission unavailable current work access head member accounting staff admin identity role appointed
Sources: src/app/shared/officeAuthority.ts; src/app/features/navigation/roleNavigation.tsx; server/help_assistant/context.py
- Actions depend on canonical account role, active state, office appointment, project participation and the record involved. A visible page or job title is not blanket write permission.
- Head, employee and Accounting responsibilities differ. A project representative is not a permanent Head; independent review approval is not permission to settle or post journals.
- For an unavailable action, read the reason, verify office/project selection, and ask the appropriate appointed Head or administrator to resolve access. Do not bypass restrictions from another screen.

## administration | Administrator account and system management | admin
Keywords: admin all users locked out accounts role defaults user access account audit settings backup export
Sources: src/app/features/navigation/sidebarContent.tsx; src/app/features/navigation/roleNavigation.tsx
- Administrator destinations include All Users, Locked out accounts, Role Defaults, User Access, Account Audit, System Settings and Backup & Export where current permissions enable them.
- Use the relevant administrative screen and review its confirmation/audit outcome. Administration does not bypass operational project access or authorize ordinary execution, cash release, settlement or posting.
- For lockout or access changes, use permitted account-management actions rather than changing financial records or granting a project role as a workaround.

## reports | Reports, dashboard counts and financial scope | head,member,accounting_staff
Keywords: report export dashboard progress percentage office year filters counts totals
Sources: src/app/features/navigation; src/app/features/budget/components/JournalEntryPage.tsx
- Reports and project/office dashboards show records available to your account. Check office, project, dates, fiscal year and status filters before comparing totals.
- Filtered lists can omit archived, deleted or inaccessible work. The assistant's visible task count is not a promise that it can read every organizational record.
- Check financial totals against the authoritative ledger and full journal entry. Commitments and cash releases are not separate expenditure to add together.

## voice_help | Typed Help and microphone dictation | head,member,accounting_staff,admin
Keywords: help assistant question sources choose project microphone dictate editable draft send
Sources: src/app/features/help-assistant/components/HelpAssistantDialog.tsx; src/app/features/help-assistant/hooks/useHelpDictation.ts
- Open Help, then Talk to eFlow AI. Choose eFlow workflows for instructions or an accessible project for recorded task blockers; inspect sources and verify important details.
- The microphone beside Send fills an editable draft. Speak, press it again to finish, correct the words, then press Send. Dictation alone does not submit the question.
- Live office budget balances, transactions, HR documents and private evidence contents are not currently queried by Help. The assistant explains their workflows and only discusses the live project/task facts it actually receives.

## live_voice | eFlow Live, Pause, Interrupt and End | head,member,accounting_staff,admin
Intents: pause speech; pause synthesis; pause microphone
Keywords: eflow live start conversation pause resume mute synthesis speaking interrupt end back chat
Sources: src/app/features/help-assistant/hooks/useHelpConversation.ts; src/app/features/help-assistant/components/HelpLiveView.tsx
- Choose eFlow Live at the top of Help for hands-free conversation. Speak in English and pause after the question so the turn can be transcribed, answered and read aloud.
- Pause pauses microphone input only; an accepted question, synthesis and playback continue. Resume re-enables listening after the reply. Interrupt or Stop reply cancels the reply; End returns to chat and closes the microphone.
- Parakeet Redux transcribes, a small LFM model selects checked guidance for Live while Qwen handles ordinary typed help, and Kitten-TTS 2 synthesizes on the AI laptop. Chunked speech can still be delayed by cold model loading or generation of later chunks.

## voice_troubleshooting | No microphone text or slow spoken replies | head,member,accounting_staff,admin
Keywords: no speech recognized meter input microphone permission runtime unavailable slow delay latency cloudflare remote browser https
Sources: src/app/features/help-assistant/services/handsFreeMicrophone.ts; server/help_assistant/speech_service.py
- If no words appear, check browser microphone permission, input selection and the meter. A moving meter proves capture, not successful server recognition; read speech-runtime or transcription errors.
- Voice needs a supported browser on localhost or HTTPS. A remote laptop sends its microphone audio through the authenticated gateway to the AI laptop, which must remain online and reachable.
- Recognition, source selection and synthesis add separate delays. Written answers may arrive before speech, and cached recordings are faster than new answers. Pausing the mic should not cancel synthesis.

## help_limits | Knowledge scope, updates and current records | head,member,accounting_staff,admin
Keywords: knowledge markdown guide facts sources version learn read system only limitations read only
Sources: server/help_assistant/knowledge.py; server/help_assistant/grounding.py; server/help_assistant/context.py
- Help reads versioned Markdown workflow passages and selects relevant permitted sources for each question. Updating the guide changes retrieved knowledge; it does not retrain the model.
- The guide describes workflows; live project/task answers use the caller's visible records. The guide cannot prove hosted deployment, migration installation or the existence of a particular transaction.
- If guidance and visible records do not answer a question, the assistant should say it cannot confirm it. It must not invent staff, balances, approvals, contacts or actions it performed.
