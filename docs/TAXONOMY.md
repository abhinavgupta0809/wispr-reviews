# Taxonomy v1 (Wispr Flow run)

Written by Claude after reading a stratified sample of 290 reviews from the Oct 12, 2026 scrape
(7,007 reviews of the Wispr Flow mobile apps, May 23, 2025 to Oct 11, 2026: every review the two
stores would serve). Machine-readable copy: `analysis/taxonomy.json`. The prompt the model sees:
`docs/annotation_prompt.md`. If these three disagree, `taxonomy.json` wins for validation and this
file gets fixed.

The six labels are the same as in the Perplexity, Indeed, and Claude runs. The categories are new.

## Labels: what kind of review is it

One or two per review. The first is the primary label.

| Label | Use when | Categories |
|---|---|---|
| Specific Praise | Positive, and names a feature, a quality, or a use case | 1-2 |
| Specific Complaint | Negative, and names a concrete problem | 1-2 |
| Feature Request | Asks for something to be added, changed, or made free | 1-2 |
| Generic Good | Positive with nothing specific ("great app", "love it") | none |
| Generic Bad | Negative with nothing specific ("worst app", "useless") | none |
| Nonsense | Unintelligible, off-topic, wrong app, abuse with no product content | none |

Rules:

- **Specific outranks generic.** "Good app but the bubble keeps vanishing" is `Specific Complaint, Generic Good`.
- **Two specific labels:** order by which takes more of the text. Tie goes to the complaint.
- **Never pair** Generic Good with Specific Praise, Generic Bad with Specific Complaint, or Generic
  Good with Generic Bad. Nonsense always stands alone.
- **Naming a use case or quality counts as specific.** "Great for emails" is Specific Praise.
- **A comparison alone is not specific.** "Gboard is better" is Generic Bad with a competitor tag.

## Categories: what part of the product

Up to two, most important first. Empty for Generic Good, Generic Bad, and Nonsense.

| Category | Covers |
|---|---|
| Transcription Accuracy | How well it hears: right or wrong words, invented or added words, dropped passages, accents, noisy rooms, whispering, names and custom dictionary words |
| AI Editing & Formatting | What it does to the text after hearing it: punctuation, capitalisation, filler-word removal, rewording, formal and casual styles, polish and grammar fixes, asking for verbatim output |
| Language Support | Quality in a language other than English, mixing or switching languages, the wrong language or script coming out, the app or its keyboard not offered in a language |
| Free Word Limit | The cap on free dictation: 1,000 or 2,000 words a week, running out of words, a limit that appeared where use was unlimited, the limit hitting mid-sentence |
| Pricing & Value | Too expensive, good value, the monthly or yearly price, regional pricing, asking for a cheaper tier or a one-time purchase |
| Billing & Subscription | Charges, refunds, cancelling, a paid plan or trial that did not apply, referral rewards not honoured |
| Customer Support | Support not answering or not resolving, automated replies; praise for a fast or helpful reply |
| Login & Account | Sign-in and sign-up failures, expired sessions, being forced to create an account before trying it, linking an existing account |
| Setup & Permissions | Onboarding that is long, confusing, or stuck; permission screens that do not register; too many settings to get started |
| Floating Bubble & Overlay | Android's floating button: it disappears, will not appear, gets in the way, the 'displaying over other apps' notice, banking and other apps refusing to open because of the overlay |
| Keyboard & App Switching | The iOS keyboard and hand-off: being bounced into the Flow app to start, the Flow keyboard's typing and autocorrect, the mic staying on, iPad and hardware-keyboard use, the Android keyboard request |
| Reliability & Bugs | Dictation that fails, returns nothing, does not paste, hangs on processing, crashes, server errors, things that broke after an update |
| Speed | How fast or slow the transcription comes back |
| Battery & Performance | Battery drain, heat, the phone or keyboard slowing down while it is installed |
| Privacy & Security | Full keyboard access, accessibility access, what is recorded or stored, cloud processing, data collection, trackers, security worries |
| Ads & Marketing | Too many ads for the app, ads that overpromise, how the reviewer heard about it |
| Desktop & Platform Parity | Mobile compared with the Mac or Windows version, features that exist on one platform only, sync across devices, asking for iPad, Linux, or watch versions |
| Notes & History | Notes and scratchpad, transcript history, deleting history, meeting notes and summaries |
| UI / UX | Layout and design, ease of use, dark mode, widgets, seeing the words while speaking, hands-free start, recording length |
| Productivity & Time Saved | Saves time, faster than typing, gets more done, changed how they work |
| Use Cases | What they use it for or who it helps: emails, messages, prompts for AI tools, coding, writing, notes, study, a disability or injury that makes typing hard |
| Other | Specific, but fits nothing above |

Tie-breakers the sample forced:

- **Hearing vs editing.** The wrong word, a missed word, or an invented word is Transcription
  Accuracy. Text that was heard right and then reworded, over-punctuated, or tidied is AI Editing &
  Formatting. A reviewer who can't tell which happened ("it gets things wrong") goes to
  Transcription Accuracy.
- **Limit vs price.** "I ran out of words" and "it used to be unlimited" are Free Word Limit.
  "$15 a month is too much" is Pricing & Value. Many reviews do both; the limit goes first when the
  reviewer was cut off, the price first when they only weighed the cost.
- **Bubble vs bugs.** Anything about the Android floating button or the overlay notice, including a
  banking app refusing to open, is Floating Bubble & Overlay. "It didn't transcribe" with no bubble
  mentioned is Reliability & Bugs.
- **App switching vs UI.** On iOS, being sent into the Flow app, the Flow keyboard's own typing,
  and the mic indicator staying on are Keyboard & App Switching. General "clunky" with no cause
  named is UI / UX.
- **Privacy vs setup.** Refusing to grant full access or accessibility access because of what it
  could read is Privacy & Security. A permission screen that won't accept the grant is Setup &
  Permissions.
- **Desktop comparisons.** "Great on my Mac, bad on my phone" is Desktop & Platform Parity plus
  whatever is bad on the phone.
- **Native dictation.** "My phone already does this" with nothing else is Generic Bad with a
  competitor tag. The competitor chart carries that signal.

## Other fields from the model

| Field | Rule |
|---|---|
| `sentiment_rating` | 1-5 from the text alone, ignoring the stars. Nonsense gets 3. |
| `language` | ISO 639-1 code of the text as written. Emoji-only or undeterminable is `und`. |
| `english_translation` | Faithful translation when the language isn't English. Empty otherwise. |
| `topic` | 2-6 lowercase English words naming the specific thing. Empty for generic and nonsense. |
| `competitors` | Products named in the text, from the fixed list. Wispr Flow's own desktop apps don't count. |
| `regression_claim` | True when the reviewer says the product got worse than it used to be. |

## Computed in code, never by the model

| Column | Rule |
|---|---|
| `rating_mismatch` | abs(stars - sentiment) >= 2 |
| `is_low_signal` | No categories. Counted in volume and ratings, excluded from topic work. |
| `is_duplicate_text` | Normalized text appears 3 or more times in the corpus. |
| `is_truncated` | Android text is 500 characters or longer (Play cuts reviews there). |
| `needs_translation` | `language` is not `en` and not `und`. |

## Coverage to keep in view

- This is the mobile apps only. Wispr Flow's Mac and Windows apps are sold directly and have no
  store reviews; desktop shows up here only when a mobile reviewer mentions it.
- The window is all time, not 90 days: the app has too few reviews for a short window. Android
  starts at its Feb 2026 launch. Apple's feed serves at most 500 reviews per storefront, so US iOS
  reaches back only to Aug 2026 while smaller storefronts reach May 2025.

## What the sample showed

Read before anything was labeled, so these were expectations to test, not findings:

- A free-plan word cap that arrived around Sept 2026 draws angry reviews from people who had used
  it unlimited for months.
- On Android the floating bubble vanishing, and banking apps blocking the overlay, recur.
- On iOS the complaint is the hand-off: being bounced into the Flow app, and the Flow keyboard.
- "Great when it works" is common: accuracy is praised while reliability is not.
- Full keyboard access and accessibility access stop some people before they try it.
- Praise clusters on accuracy against the phone's built-in dictation, time saved, and
  multilingual use; non-English quality also draws complaints.
