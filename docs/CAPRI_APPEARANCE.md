# Capri appearance

The optional appearance is a project-local SVG interpretation of Capri's mask from Cyberpunk: Edgerunners 2. The compact face measures 272 × 104 logical pixels inside a 384 × 148 transparent native window. Time and focus countdown occupy one eye, tasks and Saint Petersburg weather occupy the other. Playback controls appear below the eyes while a session is active; switching or pausing does not expand the panel.

The expanded workspace uses the same dark green, mint and pink palette across navigation, task cards, calendar, notes, weather, music, clipboard and settings. Its layout and readable type sizes stay the same. Theme styles are scoped to `.capri-theme` in `capri-theme.css`, and the canvas silhouette receives the matching fill and edge colors. Selecting Classic restores the original palette. Track notifications and staged bell reminders keep their dedicated dimensions, independent of the smaller face bounds.

The mask is `apps/desktop/src/assets/capri-mask.svg`; no remote image, animation library, video or third-party desktop-pet code is loaded. The liquid canvas stops its ambient loop while the compact face is displayed. Settings are local to the WebView profile and survive restarting. The default remains the classic island.

Visual references:

- Official character introduction: https://x.com/edgerunners/status/2120864191120621706 (green mask, black eye sockets, bright pink hair).
- Show footage reference: https://tenor.com/view/capri-cyberpunk-cyberpunk-edgerunners-cyberpunk-2077-gif-6524549678632533851
- Official series site: https://www.cyberpunk.net/en/edgerunners2

Capri and Cyberpunk: Edgerunners belong to CD PROJEKT RED, TRIGGER and Netflix. This optional appearance is a fan interpretation, not an official integration.
