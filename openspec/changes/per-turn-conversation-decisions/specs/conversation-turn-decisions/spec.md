# Spec Delta

## Purpose

Use one bounded decision batch per finalized conversation turn to select read-only retrieval needs, distinguish input and response languages, and adapt response delivery while preserving the existing conversation path when decisions are unavailable.

## ADDED Requirements

### Requirement: Valid turn decisions are applied by default
The system SHALL enable the per-turn decision phase by default and apply accepted signals to the live conversation path. It SHALL provide overall and per-group switches that restore the corresponding baseline behavior when disabled.

#### Scenario: Deployment uses default settings
- **WHEN** the feature is deployed with its documented defaults
- **THEN** valid retrieval, language, and tone decisions influence the current response rather than only being recorded as shadow observations

#### Scenario: A decision group is disabled
- **WHEN** an operator disables the tone group while language and retrieval remain enabled
- **THEN** tone uses the baseline persona and the other groups can still apply their accepted decisions

### Requirement: Finalized user turns receive one logical decision batch
The system SHALL evaluate retrieval, language, and tone signals together for each finalized user text turn when turn decisions are enabled. Provider fallback SHALL reuse that batch. Assistant, system, tool, control, partial transcript, and ephemeral media events SHALL NOT create a new conversation decision batch.

#### Scenario: Ordinary text or finalized ASR enters Chat
- **WHEN** an authorized user submits a finalized text turn through HTTP Chat or Gemini Live `send_text_turn` (including a Backend-finalized ASR transcript)
- **THEN** one logical decision batch evaluates the turn before its decisions influence retrieval and response generation
- **THEN** provider fallback uses the same question IDs and evidence

#### Scenario: Gemini Live transcribes already-streamed PCM
- **WHEN** Gemini Live reports a finalized transcript after raw PCM has already entered the active model turn
- **THEN** the system evaluates the transcript once and applies accepted retrieval policy to subsequent read-tool execution
- **THEN** the active audio response keeps the existing session language and delivery behavior because this Developer API session cannot update its setup configuration mid-turn

#### Scenario: Tool loop continues
- **WHEN** a tool result or generation retry continues the same user turn
- **THEN** the system reuses that turn's decision and does not classify the tool result as a new user request

### Requirement: Retrieval needs are independent
The system SHALL evaluate knowledge, web, and memory needs independently so multiple needs can apply to the same turn. A single exclusive intent category SHALL NOT replace these independent signals.

#### Scenario: One request needs several sources
- **WHEN** a user asks about a previously discussed product and its current public status
- **THEN** the decision can request project knowledge, past memory, and public web information together

#### Scenario: Follow-up depends on prior context
- **WHEN** the user asks "那它有保固嗎？" after discussing a product
- **THEN** the knowledge decision considers the preceding conversation rather than treating the short message as standalone social input

### Requirement: Knowledge skipping is conservative and operational
The system SHALL allow a confident negative `needs_knowledge` signal to skip mandatory knowledge retrieval independently of positive web or memory needs. Positive, uncertain, unavailable, or contradictory knowledge signals SHALL retain the existing knowledge policy. Skipping a forced lookup SHALL leave authorized knowledge tools available to the answering model.

#### Scenario: Knowledge is not needed while web is needed
- **WHEN** a turn confidently needs current public information and confidently does not need project-specific knowledge
- **THEN** the system permits a response without a mandatory knowledge lookup

#### Scenario: Knowledge signal is uncertain
- **WHEN** a knowledge signal is uncertain, unavailable, or conflicts with factual or contextual evidence
- **THEN** the existing knowledge retrieval policy applies before answering

#### Scenario: Answering model identifies missing evidence
- **WHEN** a forced lookup was skipped but the answering model identifies a need for project evidence
- **THEN** it can still call an authorized knowledge tool

### Requirement: Positive retrieval signals respect existing controls
The system SHALL apply positive read-only retrieval signals within the current mode, registry, project permissions, and recall controls. Decision results SHALL NOT make unavailable tools callable or authorize write actions.

#### Scenario: Web signal in fast mode
- **WHEN** the decision requests web information but the current mode does not offer web tools
- **THEN** the system preserves that mode restriction and does not execute a web call through the decision path

#### Scenario: Recall is disabled for the session
- **WHEN** a memory signal is positive but automatic recall is disabled for that session
- **THEN** the decision path does not re-enable automatic recall

#### Scenario: Decision cannot authorize memory writes
- **WHEN** the batch identifies useful past memory or a factual user preference
- **THEN** memory persistence still requires the existing explicit-user-intent authorization

### Requirement: Mixed input languages are identified separately
The system SHALL identify languages used by the user's own utterance, its predominant language, and whether it mixes languages. Quoted source text, model identifiers, and isolated brand names SHALL NOT alone determine the user's language.

#### Scenario: Multilingual utterance
- **WHEN** a user mixes substantive Chinese and English requests in one message
- **THEN** both input languages and a mixed-language result can be identified

#### Scenario: Quoted text is not the user's voice
- **WHEN** a Chinese question quotes a Spanish paragraph for explanation
- **THEN** the quoted paragraph alone does not require the assistant to answer in Spanish

### Requirement: Response language follows user direction and turn context
The system SHALL resolve response language separately from detected input language. An explicit user response-language request SHALL take precedence over ASR hints, detected language, and project defaults. Uncertain or unsupported classifications SHALL defer to existing language handling without discarding the user's original instruction.

#### Scenario: Explicit response language differs from input
- **WHEN** the user writes "請用英文解釋這台泵浦的保固"
- **THEN** the assistant's response-language instruction selects English even though the input is predominantly Chinese

#### Scenario: ASR translation differs from requested response
- **WHEN** ASR reports Taiwanese speech translated to Chinese text and the user explicitly requests an English response
- **THEN** the response-language instruction selects English and the original speech-language evidence remains available for retrieval

#### Scenario: Unsupported response language
- **WHEN** a user explicitly requests a language outside the configured classification choices
- **THEN** the system preserves the original language request for the answering model and does not replace it with a confident project-default instruction

### Requirement: Retrieval language is independent of response language
The system SHALL resolve knowledge retrieval language from input context and reliable speech-language evidence separately from the language requested for the final response.

#### Scenario: Translation request preserves relevant retrieval
- **WHEN** a Chinese or Taiwanese input requests an English explanation of project information
- **THEN** relevant source-language documents remain eligible for retrieval and the response can be rendered in English

### Requirement: Tone decisions affect delivery within persona constraints
The system SHALL use recognized conversational tone only to select bounded delivery hints such as clearer steps, concise reassurance, or direct wording. Uncertain tone SHALL use the existing persona style. Tone SHALL NOT change factual evidence, tool permissions, safety policy, or response-length limits.

#### Scenario: User is visibly confused
- **WHEN** the user says "你講了半天我還是不懂"
- **THEN** the response can use shorter explanations and a concrete example within the existing persona and length constraints

#### Scenario: Urgency is a tone signal
- **WHEN** a message is classified as urgent
- **THEN** wording can prioritize actionable steps without treating that classification as clinical or safety authority

### Requirement: Complete decision failure restores the baseline path
The system SHALL continue the conversation using existing retrieval, recall, response-language, and persona behavior when all eligible providers fail, configuration is unavailable, the decision deadline expires, or turn decisions are disabled. The optional decision phase SHALL NOT itself cause Chat or Live failure.

#### Scenario: Four fallback hops fail
- **WHEN** Clef primary, Clef backup, Jev, and OpenAI fail within the decision budget
- **THEN** the conversation proceeds using the pre-decision feature policies and can still produce a reply

#### Scenario: Administrator disables all providers
- **WHEN** no provider remains eligible because providers are disabled or their required credentials are unavailable
- **THEN** the turn follows the baseline path without attempting unauthorized providers

#### Scenario: One signal is uncertain
- **WHEN** a valid batch contains a usable language result but an uncertain knowledge result
- **THEN** the usable result can apply while knowledge retrieval follows its baseline policy

#### Scenario: Later hooks observe the same dependency outage
- **WHEN** the turn-decision phase has exhausted the provider chain and a later decision-dependent hook runs in that turn
- **THEN** it uses its existing no-decision fallback instead of repeating the unavailable provider chain for that turn

### Requirement: Decision state is bound to its own turn
The system SHALL bind decision outcomes to the originating session, project, and turn revision. Superseded, cancelled, or completed-turn outcomes SHALL NOT steer a later turn or become long-term user tone labels.

#### Scenario: New turn supersedes a pending decision
- **WHEN** another user turn or a newer revision arrives while a decision is pending
- **THEN** the old result cannot change the new turn's retrieval or language

#### Scenario: Tone is not persisted as a user profile
- **WHEN** a turn completes with a frustration or confusion signal
- **THEN** the system does not save that signal as a user trait or write it to long-term memory

### Requirement: Decision input and telemetry have defined boundaries
The system SHALL send only bounded current-user text, recent user/assistant context, allowed language choices, and relevant project-policy hints to turn-decision providers. It SHALL exclude secrets, account identifiers, system/persona prompts, and raw tool or knowledge content. Telemetry SHALL record provider, timing, policy outcome, and fallback reason without raw conversation or tone labels.

#### Scenario: Decision evidence is constructed
- **WHEN** the turn-decision request is built
- **THEN** it contains only the documented allowlisted evidence and remains within the configured input budget

#### Scenario: Outcome is recorded
- **WHEN** the decision succeeds or degrades
- **THEN** usage and diagnostics show the selected hop, duration, routing application or fallback reason without storing the user's text or emotional classification

### Requirement: Decision work has a shared deadline
The system SHALL bound the complete turn-decision phase with a wall-clock deadline including configuration lookup and fallback hops. Cancellation SHALL stop obsolete decision work, and later hops SHALL be attempted only within the remaining budget.

#### Scenario: A provider stalls
- **WHEN** a provider consumes its allowed attempt time
- **THEN** it is cancelled and the next eligible hop can use the remaining budget

#### Scenario: Shared deadline is exhausted
- **WHEN** the turn-decision budget expires before a complete answer is available
- **THEN** the baseline conversation path starts without waiting for late decisions
