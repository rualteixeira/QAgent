1. Platform Overview

1.1 Introduction
testingON is a test automation platform that lets a single team design, execute, and monitor tests across multiple types of applications — Web, Mobile, and REST/SOAP services — from one unified workspace. It is built as a set of cooperating microservices behind a single API gateway, with a web frontend used for day-to-day operation.

Beyond executing tests, testingON also acts as an authoring and orchestration hub: it stores reusable applications, pages and objects, groups tests into execution plans, schedules recurring runs, and pushes results and notifications back to the teams and tools that need them.

1.2 Current Version

This chapter documents the platform as of the following release, per the product changelog:

* Version: testingON Kepler — 2026.1.2 (13 Jul 2026)

Highlights carried over from the previous release (Kepler — 2026.1.1, 06 Mar 2026) and still part of the current platform:

* Unified testing framework supporting Web, API, Mobile, and composite test scenarios
* High-performance test execution engine with parallel execution and detailed reporting
* AI-powered user story generation from user input and RAG contextual data
* AI-driven test case generation from user stories, enriched with contextual knowledge (RAG)
* Natural-language-based test creation and execution
* Natural-language querying and execution of repository test cases
* GenAI assistant for contextual support, guidance, and interactive user assistance
* Autonomous smart agents that discover new user stories and generate tests automatically
* Self-healing test execution with dynamic object resolution
* Automated script generation (Selenium, Playwright, Robot Framework) from executed test flows

The 2026.1.2 release itself focused on stability and quality-of-life work, plus several functional additions covered throughout this documentation set:

* A guided Getting Started onboarding panel on the Home page (section 1.7)
* Record & Play for Mobile, with a full element Inspector (section 2.7)
* Objects shared between Web and Mobile, and the ability to move objects between applications/pages (section 2.2)
* Changed Datapool file delivery — no longer emailed as a download link (section 6.8)
* Generate Test TestingON in Custom Autonomous Execution — review and edit a generated test before pushing it to the repository (section 8.4)
* Monitoring split into dedicated Task Monitoring and Execution Monitoring views (Chapter 5)
* Expanded Alert Management with five configurable alert types (section 6.9)
* Bug fixes across all pages, and layout/overlay corrections
* Drag-and-drop and positioning fixes
* Field visibility and glossary display improvements
* Execution plan and scheduling stability improvements
* Datapool handling and synchronization fixes
* Execution history and repository reporting accuracy improvements
* Enhanced issue and test type flexibility
* Notification and user information updates

1.3 Key Capabilities

At a functional level, testingON covers the following areas (each is expanded in its own chapter later in this documentation set):

* Test authoring — create and organize tests by project, version and cycle, built from reusable keywords and steps, across Web, Mobile, API and Image-recognition applications.
* Application modeling — register applications, pages and UI objects that tests reference, so element locators are managed centrally rather than hard-coded per test.
* Multi-technology execution — run Web and Mobile UI tests and REST/SOAP API tests from the same platform.
* Execution plans and scheduling — group tests into execution plans and schedule them to run automatically.
* Self-healing execution — dynamically resolve UI objects at runtime so tests keep working through minor UI changes.
* GenAI features — generate user stories and test cases from natural language, ask an AI assistant for guidance, run automation described in natural language, and let smart agents propose new tests from discovered user stories.
* Monitoring — track running/queued tasks and executions in real time.
* Repository integrations — exchange test cases, issues and results with external test/issue management tools.
* Notifications & Alerts — email/in-app notifications about execution outcomes, plus configurable alert rules for platform activity.
* Configuration & administration — manage environments, users, device labs, execution machines, global variables, alerts and other platform-wide settings.

# Platform Architecture

testingON follows a **microservices architecture**. A single **API Gateway** acts as the entry point for both the frontend and external consumers, routing requests to a set of specialized backend microservices.

## Microservices Overview

| Component | Functional Role |
|------------|----------------|
| **API Gateway** | Single entry point for the frontend. Authenticates requests (JWT) and routes them to the appropriate backend microservice. |
| **Core** | Central test management domain, including tests, applications, pages, objects, keywords, execution history, and related core entities. |
| **Configurations** | Platform-wide administration and configuration, including environments, users, device labs, alerts, global variables, and other settings. |
| **Executions - Web/Mobile** | Executes Web and Mobile UI automated tests. |
| **Executions - REST/SOAP** | Executes API tests against REST and SOAP services. |
| **Scheduler** | Schedules execution plans to run automatically at predefined times or intervals. |
| **Notifications & Activity** | Sends notifications (e.g., email) and tracks platform activity. |
| **Repository Integrations** | Integrates testingON with external repository and issue-management platforms for test and issue synchronization. |
| **GenAI** | Provides AI-powered capabilities, including user story generation, test case generation, the AI assistant, and smart agents. |
| **File Service** | Manages upload, storage, and retrieval of files used by the platform, such as execution artifacts and uploaded documents. |

## Frontend

The frontend is a **React/TypeScript Single-Page Application (SPA)** that consumes the **API Gateway**. It serves as the primary user interface through which end users access and interact with all platform capabilities described in Section 1.3.

# Repository & Tool Integrations

The **Repository Integrations** component connects testingON with external test management, issue tracking, and application lifecycle management (ALM) platforms. Based on the integration handlers present in the current codebase, the following systems are supported:

| Integration | Description |
|------------|-------------|
| **Jira / Xray** | Synchronization of test cases, test executions, and results with Jira and Xray. |
| **Azure DevOps** | Synchronization with Azure DevOps work items, test plans, and test results. |
| **Zephyr** | Synchronization of test assets and execution data with Zephyr Test Management. |
| **TM (Test Manager)** | Synchronization with a Test Manager repository. |

These integrations enable test cases, execution results, and issues to remain synchronized between testingON and the external tool already used by a client team for test management and defect tracking. This allows organizations to maintain a single source of truth while leveraging testingON's automation and execution capabilities alongside their existing development and quality assurance workflows.

# Scope and Notes

This chapter provides an overview of the testingON platform. Each capability introduced in Section 1.3 is documented in detail in the subsequent chapters:

- **Chapter 2:** Test Creation & Applications
- **Chapter 3:** Test Execution & Execution Plans
- **Chapter 4:** Scheduler
- **Chapter 5:** Monitoring
- **Chapter 6:** Configurations & Administration
- **Chapter 7:** Repository Integrations & Web Service Testing
- **Chapter 8:** GenAI Features

The information presented throughout this documentation is based directly on the current testingON source code, including module structures, configuration files, controller definitions, and the in-product changelog. Feature descriptions related to versions **2026.1** and **2026.1.2** are additionally supported by the corresponding release documentation.

Where functionality, workflows, or user interface behavior could not be fully validated from the available source materials, or where verification against a live platform instance was not possible, this limitation is explicitly identified. Such observations are typically documented in the **"Notes on the Illustrations"** section found at the end of each chapter to ensure clear distinction between verified implementation details and inferred behavior.

# Getting Started

The **Getting Started** panel is an interactive onboarding feature available from the **Home** page. Its purpose is to help new users configure the automation environment and prepare the platform for test creation and execution.

Users can access the panel from the top navigation bar, next to **Help**. The workflow guides them through five essential setup steps, ensuring that all required integrations, credentials, and execution resources are in place before they begin using the platform.

*Figure: Home page with the Getting Started entry point (top navigation, next to Help).*

## Guided Setup Process

The panel tracks completion status and preserves progress, allowing users to resume configuration from the exact point where they previously stopped.

### 1. Connect the Repository Server

Configure a connection to the team's repository or test management platform, such as:

- Jira
- Xray
- Azure DevOps

One server must be marked as the active repository. Repository entities such as projects, versions, and test cycles are retrieved from the external system rather than being created directly within testingON. As a result, an empty **Project** selection list typically indicates that this step has not been completed.

### 2. Add Repository Credentials

Each user must authenticate individually using their own API token or repository credentials.

While the repository server configuration is shared across the platform, user credentials are stored separately. This ensures that test updates, executions, and issue synchronization operations are performed under the correct user identity and are attributed appropriately within the connected repository.

### 3. Set Up Machines and Devices

Execution resources must be configured before automated tests can run successfully.

Depending on the testing scope, users should:

- Register at least one execution machine for Web testing.
- Configure a connected device lab for Mobile testing.

Tests can be authored without completing this step; however, execution requests will remain queued indefinitely if no compatible execution resource is available.

### 4. Create and Run the First Web Test

This step launches a guided walkthrough that introduces the core test creation workflow.

The tutorial walks users through the actual platform screens and concludes with a saved test that is ready to execute, providing a practical introduction to test authoring and execution.

### 5. Enable GenAI Features

To use AI-assisted capabilities, a GenAI server connection must be configured.

Once connected, teams can populate the platform's Retrieval-Augmented Generation (RAG) knowledge base with their own requirements, standards, specifications, and best practices. Generated user stories, test cases, and AI-assisted recommendations can then align with the organization's established conventions and quality processes.

## Progress Tracking

The Getting Started panel includes:

- A progress indicator showing how many of the five setup steps have been completed.
- Dedicated action buttons for each step, such as **Configure**, **Add Credentials**, and **Start Tour**.
- Persistent progress tracking that allows users to resume onboarding without repeating completed work.

*Figure: Getting Started panel showing all five steps completed, each with its corresponding action button.*

By exposing the required action directly within each step and providing clear progress visibility, the Getting Started panel helps reduce configuration errors, accelerate onboarding, and ensure that new users can begin creating and executing tests with minimal setup friction.

2. Test Creation & Applications

# Overview

This chapter covers the two functional areas grouped under the **Create** section of testingON:

- **Application Modeling**: defining and maintaining the applications under test through **Applications**, **Pages**, and **Objects**.
- **Test Authoring**: creating automated tests based on those application models.

These capabilities support all testing technologies currently available in the platform, including:

- **Web Testing**
- **Mobile Testing**
- **API Testing (REST and SOAP)**
- **Image Recognition Testing**

All functionality described in this chapter is provided by the **Core** module and backed by the **Core microservice**, which serves as the central domain layer for test management within testingON.

The application model created through Applications, Pages, and Objects forms the foundation upon which automated tests are built. In turn, these tests become the basis for other platform capabilities, including test execution, execution plans, scheduled runs, result tracking, and self-healing mechanisms.

Understanding the concepts and workflows presented in this chapter is therefore essential, as they underpin the majority of testingON's automation lifecycle and are reused throughout the remaining platform features.

# Overview

This chapter covers the two functional areas grouped under the **Create** section of testingON:

- **Application Modeling**: defining and maintaining the applications under test through **Applications**, **Pages**, and **Objects**.
- **Test Authoring**: creating automated tests based on those application models.

These capabilities support all testing technologies currently available in the platform, including:

- **Web Testing**
- **Mobile Testing**
- **API Testing (REST and SOAP)**
- **Image Recognition Testing**

All functionality described in this chapter is provided by the **Core** module and backed by the **Core microservice**, which serves as the central domain layer for test management within testingON.

The application model created through Applications, Pages, and Objects forms the foundation upon which automated tests are built. In turn, these tests become the basis for other platform capabilities, including test execution, execution plans, scheduled runs, result tracking, and self-healing mechanisms.

Understanding the concepts and workflows presented in this chapter is therefore essential, as they underpin the majority of testingON's automation lifecycle and are reused throughout the remaining platform features.

# Creating a Test

Tests are created and maintained through the **Create → Tests** area of testingON.

Each test is organized within the repository structure and is associated with:

- A **Project**
- A **Version**
- A **Cycle**

These elements are displayed in a hierarchical tree on the left side of the screen, allowing users to navigate through existing tests and organize them according to their repository structure.

In addition to its repository location, every test includes:

- A **Name**
- A **Description** (free-text)
- One or more **Labels**

Labels are commonly used to categorize and filter tests, for example:

- `smoke`
- `regression`
- `sanity`
- `critical-path`

This metadata helps teams manage large test suites and identify specific sets of tests for execution or reporting purposes.

## Environment Selection

Each test must be associated with an **Environment**.

The selected environment determines the execution context used when:

- Running the test
- Debugging the test
- Launching executions from execution plans

Environment configuration typically includes the target URLs, infrastructure, devices, and environment-specific settings required during execution.

## Advanced Options

An **Advanced Options** section provides additional test configuration settings.

One of the available settings is the **Threshold**, which represents the expected maximum execution duration for the test.

This value is later used by testingON's monitoring capabilities to:

- Track execution performance over time
- Highlight unusually slow executions
- Surface duration-related metrics within the Monitoring dashboards

By defining realistic thresholds, teams can more easily identify performance regressions and execution anomalies.

*Figure 2.2 - Test creation and editing screen, showing the step list for a Web test.*

## Unified Test Editing Experience

The overall test creation and editing experience is consistent across all supported testing technologies.

The same screen layout and step-based model are used regardless of whether the user is creating:

- Web tests
- Mobile tests
- REST API tests
- SOAP API tests
- Image-recognition tests

While the editor framework remains the same, certain step types and configuration options vary depending on the selected testing technology.

The technology-specific capabilities are described in the following sections:

- **Section 2.5 - API Testing (REST/SOAP)**
- **Section 2.6 - Image-Recognition Testing**
- **Section 2.7 - Record & Play (Rec & Play)**

This common editing model reduces the learning curve for users by providing a consistent authoring experience across all automated testing approaches supported by testingON.

# Test Steps

The core of every test in testingON is an ordered sequence of **steps**. Each step represents an action to be performed during execution and is based on a **keyword**, such as:

- **Open Browser**
- **Fill Element**
- **Click Element**
- **Assert Element Visible**

A step combines the selected keyword with the parameters required to execute it. These parameters typically include:

- An Object defined in the Application model (see Section 2.2)
- A literal value supplied by the user
- A combination of both

Together, the keyword and its parameters define the behavior executed at runtime.

## Step List

Test steps are displayed in a tabular format within the test editor.

Each row provides the following capabilities:

### 1. Step Selection

A checkbox is displayed for every row, allowing multiple steps to be selected simultaneously.

This selection can be used for bulk operations such as:

- Deleting multiple steps
- Executing actions against multiple selected entries

### 2. Sequence Number

Each step is assigned a sequence number that determines its execution order.

The sequence value can be edited directly, allowing users to reorder steps without recreating them.

### 3. Keyword and Parameters

The main content of the row displays:

- The selected keyword
- Its resolved parameters

This information is presented prominently to make the execution flow easy to follow.

If the step includes a description, that description is shown below the keyword when the step is displayed in its collapsed state.

### 4. Row Actions

Each step provides several actions directly within the row:

| Action | Description |
|----------|-------------|
| **Duplicate** | Creates a copy of the step. |
| **Delete** | Removes the step from the test. |
| **View Debug Result** | Displays the most recent debugging result associated with the step. |
| **View Screenshot** | Opens the screenshot captured during the last debugging session, when available. |
| **Run Step** | Executes the step individually without running the entire test. |

These actions simplify test construction, troubleshooting, and maintenance.

## Reusable Building Blocks

A test is not limited to individual steps.

Additional reusable and structural elements can be inserted through the controls located below the step table.

### Templates

A **Template** is a reusable collection of predefined steps maintained separately from individual tests.

When inserted into a test, the template behaves as a single reusable building block, allowing common workflows to be standardized and shared across multiple test cases.

Typical examples include:

- Login sequences
- User setup activities
- Data preparation workflows
- Common navigation paths

### Logic Keywords

A **Logic** keyword introduces structured control-flow behavior into a test.

Rather than executing steps strictly from top to bottom, logic elements allow tests to make decisions dynamically during execution.

Supported constructs include:

- Conditional execution
- Alternative execution paths
- Looping structures

The details of these control-flow capabilities are described in the following section.

---

# Test Steps

The body of a test is its ordered list of steps. Each step wraps a keyword (the action to perform, e.g. "Open Browser", "Fill Element", "Click Element", "Assert Element Visible") together with the parameters it needs — typically one of the Objects registered against the application (section 2.2), a literal value, or both.

Steps render as a table with:

1. A checkbox per row, to select multiple steps for bulk actions (e.g. delete).
2. The step's sequence number, editable directly to reorder it.
3. The keyword and its resolved parameters in bold, with the step's optional description shown underneath when collapsed.
4. Row actions to duplicate or delete the step, attach/view its last debugging result (including a screenshot), and run it individually.

Beyond individual steps, a test can also insert a Template (a reusable, named block of steps defined elsewhere and dropped in as a unit) or a Logic keyword (conditional/looping constructs such as if/else blocks) via the buttons below the steps table.

The two building blocks that go beyond a flat step list — Request Blocks for API tests and structured Logic flows — are detailed next.

## Structured Logic Flows

Logic steps let a test encode conditional decisions directly in its step list: an `IF` keyword opens a condition, optional `AND` / `ELSE` branches follow, and `END` closes the block — with the steps inside each branch indented to show which condition they belong to.

*A Logic test: nested IF / AND / ELSE / END steps controlling which actions run.*

# API Testing (REST/SOAP)

testingON authors and runs API tests against REST and SOAP services using the same test/step model as Web and Mobile (section 2.4), executed by the dedicated REST/SOAP microservice (section 1.4). Selecting the REST or SOAP application type surfaces API-specific keywords — issuing a request (GET/POST/etc. with a URL), asserting on the response, and storing parts of the response into variables for later steps.

## Request Blocks

Consecutive steps that belong to the same HTTP request are grouped and visually highlighted as a **Request Block** ("Request Block #1", "#2", ...). This makes it easy to see, at a glance, which steps configure and validate one call versus the next.

*A REST test: two Request Blocks (GET, then POST), with response values stored into variables between them.*

testingON also validates block structure automatically: it flags when a Request Block does not contain all the keywords required to close it correctly, so a malformed request definition is caught before the test is run rather than failing unexpectedly during execution. Inserting a non-request step (e.g. "Store Response") starts a new block.

*testingON flags a Request Block that is missing required keywords, guiding the step order needed to close it correctly.*

# Image-Recognition Testing

Image-recognition-based is one of the three Application types (alongside Web and Mobile, section 2.2). Instead of locating elements through DOM selectors or native accessibility identifiers, an Image-recognition application drives interaction by matching screen regions against reference images: a step targets a captured image of the element (a button, icon, or field) rather than an XPath or Resource ID, and testingON locates that image on screen at runtime to click, read, or assert against it.

This makes it suited to interfaces that don't expose a reliable accessibility tree — for example, legacy desktop applications, kiosks, or embedded/virtualized screens — where Web or native Mobile locators aren't available. Because Rec & Play's step-by-step interaction capture relies on reading the application's element tree, it is **not available for Image-recognition applications** (section 2.7); steps are built from captured reference images instead.


