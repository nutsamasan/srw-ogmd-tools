# Will behavior profiles

Hit = your attack lands. Miss = your attack fails to hit. Evade = you avoid an enemy attack. Take damage = you receive damage. Ally lost = a unit on your side is shot down.

KO bonus is the extra personality bonus for defeating an enemy. It is added to the normal +1 defeat gain: a +3 bonus gives a +4 defeat component. Hit gains and other modifiers are separate.

These are base event responses, not guaranteed totals for a whole battle. Twin/support attacks, MAP attacks, skills, Ace bonuses, scripted events and the Will cap can change the result. Choosing a profile changes how Will rises or falls; it does not set current Will, the starting value or the cap.

| Profile / example pilots | Hit | Miss | Evade | Take damage | KO bonus | Ally lost |
|---|---:|---:|---:|---:|---:|---:|
| 0: Eita / Azuki | 0 | 0 | 0 | +1 | +3 | 0 |
| 1: Kyosuke / Ryusei | +2 | -1 | 0 | +2 | +3 | +2 |
| 2: Kusuha / Akimi | +1 | +1 | +1 | +1 | +3 | +1 |
| 3: Rai / Latooni | +2 | 0 | +2 | +1 | +1 | 0 |
| 4: Russel / Ibis | 0 | 0 | +1 | +1 | +3 | +1 |
| 5: Excellen / Arado | 0 | +3 | +1 | +2 | +3 | 0 |
| 6: Lefina / Mizuho | +1 | -2 | +1 | +1 | +3 | -1 |
| 7: Katina | 0 | +2 | 0 | +2 | +4 | +2 |
| 8: Helluga / Gu-Landon | +3 | +4 | +3 | +4 | +4 | +3 |
| 9: Rishu / Shu | +2 | +3 | +2 | +3 | +4 | +3 |
| 10: Kinaha / Crystal Dragoon | +1 | +1 | +3 | +2 | +3 | +2 |
| 11: Kalo-Ran / So-Des | +1 | +2 | +1 | +3 | +3 | +2 |

## Choosing a profile

- **0: Eita / Azuki** — Slow growth: taking damage and defeating enemies are its main sources of Will.
- **1: Kyosuke / Ryusei** — Rewards landing hits and taking damage. Missing costs 1 Will; evading gives none.
- **2: Kusuha / Akimi** — Balanced: gains 1 Will from hits, misses, evading and taking damage, with no negative responses.
- **3: Rai / Latooni** — Rewards accurate attacks and evasion. Its defeat bonus is smaller than most profiles.
- **4: Russel / Ibis** — Gains Will from evading and taking damage, but neither hits nor misses add Will.
- **5: Excellen / Arado** — Rewards misses more than hits: a miss gives 3 Will, while a landed hit gives none.
- **6: Lefina / Mizuho** — Gains from hits, evasion and damage, but loses 2 Will on a miss and 1 when an ally is lost.
- **7: Katina** — Rewards misses, damage and defeats. Hits and evasion alone give no Will.
- **8: Helluga / Gu-Landon** — The highest native gains overall: every response is positive and none is below another profile.
- **9: Rishu / Shu** — High gains in every category, especially misses, damage and defeats.
- **10: Kinaha / Crystal Dragoon** — Especially rewards evasion: evading gives 3 Will, with positive gains in every category.
- **11: Kalo-Ran / So-Des** — Especially rewards taking damage, with positive gains in every category.

Values and event paths were inspected in the PS3 game data and executable. See `FORMAT_NOTES.md` for the evidence and limits. In-game validation of edited profiles is pending.
