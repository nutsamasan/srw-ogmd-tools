"""Player-facing explanations of the six native Will response columns."""
from pilot_patch import PERSONALITIES

EVENTS = ('Hit', 'Miss', 'Evade', 'Take damage', 'KO bonus', 'Ally lost')
EXPLANATIONS = {
    0: 'Slow growth: taking damage and defeating enemies are its main sources of Will.',
    1: 'Rewards landing hits and taking damage. Missing costs 1 Will; evading gives none.',
    2: 'Balanced: gains 1 Will from hits, misses, evading and taking damage, with no negative responses.',
    3: 'Rewards accurate attacks and evasion. Its defeat bonus is smaller than most profiles.',
    4: 'Gains Will from evading and taking damage, but neither hits nor misses add Will.',
    5: 'Rewards misses more than hits: a miss gives 3 Will, while a landed hit gives none.',
    6: 'Gains from hits, evasion and damage, but loses 2 Will on a miss and 1 when an ally is lost.',
    7: 'Rewards misses, damage and defeats. Hits and evasion alone give no Will.',
    8: 'The highest native gains overall: every response is positive and none is below another profile.',
    9: 'High gains in every category, especially misses, damage and defeats.',
    10: 'Especially rewards evasion: evading gives 3 Will, with positive gains in every category.',
    11: 'Especially rewards taking damage, with positive gains in every category.',
}
GUIDE_NOTES = (
    'Hit = your attack lands. Miss = your attack fails to hit. Evade = you avoid an enemy attack. '
    'Take damage = you receive damage. Ally lost = a unit on your side is shot down.\n\n'
    'KO bonus is the extra personality bonus for defeating an enemy. It is added to the normal '
    '+1 defeat gain: a +3 bonus gives a +4 defeat component. Hit gains and other modifiers are separate.\n\n'
    'These are base event responses, not guaranteed totals for a whole battle. Twin/support attacks, '
    'MAP attacks, skills, Ace bonuses, scripted events and the Will cap can change the result. '
    'Choosing a profile changes how Will rises or falls; it does not set current Will, the starting value or the cap.'
)


def signed(value):
    return f'+{value}' if value > 0 else str(value)


def summary(profile):
    values = PERSONALITIES[profile]['native_response_values']
    parts = [f'{event} {signed(value)}' for event, value in zip(EVENTS, values)]
    return ' · '.join(parts[:3]) + '\n' + ' · '.join(parts[3:])


def markdown_guide():
    lines = ['# Will behavior profiles', '', GUIDE_NOTES, '',
             '| Profile / example pilots | ' + ' | '.join(EVENTS) + ' |',
             '|---|' + '---:|' * len(EVENTS)]
    for pid, item in PERSONALITIES.items():
        lines.append(f"| {pid}: {item['name']} | " + ' | '.join(map(signed, item['native_response_values'])) + ' |')
    lines += ['', '## Choosing a profile', '']
    for pid, item in PERSONALITIES.items():
        lines.append(f"- **{pid}: {item['name']}** — {EXPLANATIONS[pid]}")
    lines += ['', 'Values and event paths were inspected in the PS3 game data and executable. '
              'See `FORMAT_NOTES.md` for the evidence and limits. In-game validation of edited profiles is pending.', '']
    return '\n'.join(lines)
