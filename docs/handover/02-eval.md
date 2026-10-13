# Phase 02 gold-set evaluation

Gold rows: 120

Rows with annotation_error: 0

## Agreement

| Metric | Matches | Rows | Value | Target | Status |
| --- | --- | --- | --- | --- | --- |
| Primary label accuracy | 113 | 120 | 94.17% | 85.00% | PASS |
| Label set overlap | 114 | 120 | 95.00% | — | — |
| Primary category agreement | 83 | 92 | 90.22% | 80.00% | PASS |
| Low-signal agreement | 24 | 28 | 85.71% | — | — |
| Sentiment within one point | 120 | 120 | 100.00% | — | — |

Sentiment mean absolute error: 0.2583 over 120 scored rows. Missing/failed sentiment rows: 0. Within-one-point accuracy uses every gold row; missing/failed results count as misses. Failed annotations also count as misses on label/category/low-signal metrics.

## Primary-label confusion matrix

| Gold primary label | Specific Praise | Specific Complaint | Feature Request | Generic Good | Generic Bad | Nonsense | (missing) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Specific Praise | 28 | 1 | 0 | 1 | 0 | 0 | 0 |
| Specific Complaint | 0 | 55 | 0 | 0 | 0 | 0 | 0 |
| Feature Request | 0 | 0 | 7 | 0 | 0 | 0 | 0 |
| Generic Good | 2 | 0 | 0 | 19 | 0 | 1 | 0 |
| Generic Bad | 0 | 2 | 0 | 0 | 2 | 0 | 0 |
| Nonsense | 0 | 0 | 0 | 0 | 0 | 2 | 0 |

## Per-category agreement

Gold count includes each row whose gold category set contains that category. A match requires the model's primary category to equal that category; a two-category gold row can appear in two denominators.

| Category | Gold count | Primary-category matches | Agreement |
| --- | --- | --- | --- |
| Transcription Accuracy | 24 | 19 | 79.17% |
| AI Editing &amp; Formatting | 8 | 6 | 75.00% |
| Language Support | 6 | 3 | 50.00% |
| Free Word Limit | 6 | 5 | 83.33% |
| Pricing &amp; Value | 5 | 2 | 40.00% |
| Billing &amp; Subscription | 4 | 3 | 75.00% |
| Customer Support | 1 | 0 | 0.00% |
| Login &amp; Account | 4 | 4 | 100.00% |
| Setup &amp; Permissions | 0 | 0 | n/a |
| Floating Bubble &amp; Overlay | 7 | 5 | 71.43% |
| Keyboard &amp; App Switching | 7 | 5 | 71.43% |
| Reliability &amp; Bugs | 18 | 9 | 50.00% |
| Speed | 4 | 2 | 50.00% |
| Battery &amp; Performance | 0 | 0 | n/a |
| Privacy &amp; Security | 3 | 3 | 100.00% |
| Ads &amp; Marketing | 2 | 2 | 100.00% |
| Desktop &amp; Platform Parity | 9 | 2 | 22.22% |
| Notes &amp; History | 1 | 0 | 0.00% |
| UI / UX | 5 | 3 | 60.00% |
| Productivity &amp; Time Saved | 12 | 7 | 58.33% |
| Use Cases | 7 | 3 | 42.86% |
| Other | 0 | 0 | n/a |

## All label/category/low-signal disagreements (15)

Every disagreement on primary label, primary category, or low-signal agreement is included once. Text is sliced to 300 Unicode characters before Markdown escaping; no row limit is applied.

| Review ID | Stars | Review text (first 300 characters) | Gold labels | Gold categories | Model labels | Model categories | Model topic |
| --- | --- | --- | --- | --- | --- | --- | --- |
| play_6ea8025f-b0b2-4176-be76-1705bd0a4902 | 1 | doesn't work on new androids | Generic Bad |  | Specific Complaint | Reliability &amp; Bugs | doesn't work new androids |
| play_16b4bf76-6bca-4ddf-8898-f8985897f498 | 1 | Unnecessary hyping . It's not better than normal native Android or inside WhatsApp or Gemini speech to text. Just marketing and hype. I had some issues with native phone capacity and observed same issues here too. Huge disappointment. | Generic Bad |  | Specific Complaint | Ads &amp; Marketing | overhyped marketing |
| play_58335f20-75ae-4b0d-bafd-756b6e8979fc | 2 | would like to improve the ratings: only one thing can improve transcription it fails yaar. | Specific Complaint | Reliability &amp; Bugs | Specific Complaint | Transcription Accuracy | transcription fails |
| play_ae4dd558-9c13-42ae-9958-db364bea0ded | 3 | "So were the changes the developers made which caused this?" That sentence makes no sense grammatically. Wispr Flow won't write what I actually said, which is: "So was it the changes the developers made which caused this?" | Specific Complaint | Transcription Accuracy | Specific Complaint | AI Editing &amp; Formatting | rewrites words grammar |
| play_8ecf4d48-de05-4641-b991-0ecc896321dd | 3 | come si riesce a cancellare i messaggi che mandi dopo la trascrizione.Vorrei sapere. | Feature Request | Notes &amp; History | Feature Request | Other | delete sent message after transcription |
| play_518f9a2e-8511-473c-9eec-0385bce9abde | 4 | I'm in the sweet 5 star because, when you send the first audio, it captures normal and does the translation. But when I try again I need to leave the conversation and come back so he can continue fundraising. He is not able to recognize it. | Specific Complaint | Reliability &amp; Bugs | Specific Complaint, Specific Praise | Transcription Accuracy, Language Support | fails on second recording |
| play_08c1894c-0966-4c02-9301-4080f0da91f4 | 4 | can I replace Gboard mic to wispr flow every time I need to press the button after completing the talk | Feature Request | Keyboard &amp; App Switching | Feature Request | UI / UX | replace gboard mic button |
| play_bfcbc5ff-3c46-4ef5-8d64-708cf01f5046 | 4 | The dictation is great, really life changing for someone who has to reply to a lot of email. I would give another star if you can fix the problem of the app disappearing. For now I need to force stop, restart and reapply permissions frequently. Thanks to your support for that workaround. | Specific Complaint \| Specific Praise | Floating Bubble &amp; Overlay \| Use Cases | Specific Complaint, Specific Praise | Reliability &amp; Bugs, Setup &amp; Permissions | app disappears frequently |
| play_552839f3-2f1a-4676-9021-cd1b0750f519 | 5 | Writing this review out with Wispr Flow - lazy man's keyboard. Never typing again. | Generic Good |  | Specific Praise | Productivity &amp; Time Saved | replaces typing |
| play_a220102b-c858-4218-bfec-980175eda915 | 5 | Excellent speech-to-text app, better than anything else I've used across Android or Windows. One issue I've noticed is that on Android it sometimes converts the text but fails to paste it in the target text box. As a workaround I go to the Wispr app, find the text, copy it from there and paste it in | Specific Praise \| Specific Complaint | Productivity &amp; Time Saved \| Reliability &amp; Bugs | Specific Complaint, Specific Praise | Reliability &amp; Bugs, Desktop &amp; Platform Parity | text not pasted on android |
| play_3e7bf7c0-438b-48f3-bf35-8824d1fd0de2 | 5 | This app is more than 5 star rating for the excellent work it's doing. It sure deserves more than that. Great jobs guys for making me type less with stress free methods. | Generic Good |  | Specific Praise | Productivity &amp; Time Saved | saves typing effort |
| play_47bd6a34-077e-4b35-a91d-43cf82a838ce | 5 | this app is useful and has been doing good on english language | Specific Praise | Transcription Accuracy | Specific Praise | Language Support | good english support |
| ios_13598205547 | 5 | Bra | Generic Good |  | Nonsense |  |  |
| ios_13461965953 | 5 | This has been a game-changing app for me. I use it on my Mac as well to do my work, and it has given me a long-awaited solution to the horrible keyword experience problem that we all have. Yes, I wrote this review with Wispr Flow. | Specific Praise | Desktop &amp; Platform Parity | Generic Good |  |  |
| ios_12735216046 | 5 | I really don't like typing on a touchscreen, but I have to respond quickly to a lot of messages in my work as a business owner. This amazing app solves that problem. I'm able to respond quickly to messages on the go without having to do lots of editing of poor quality voice typing, and without sendi | Specific Praise | Productivity &amp; Time Saved \| Use Cases | Specific Praise | AI Editing &amp; Formatting, Productivity &amp; Time Saved | saves time on messages |
