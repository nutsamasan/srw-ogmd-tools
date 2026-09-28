"""Display and storage conventions for the game's separate text formats."""


def battle_display(text):
    # The native BMD splitter runs before the renderer and recognizes '/'.
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('/', '\n')


def battle_storage(text):
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '/')


def wrap_battle(metrics, text, cell, limit):
    # Keep authored BMD line boundaries. Wrap only inside each existing line.
    return '/'.join(metrics.wrap(line, cell, limit).replace('\n', '/')
                    for line in battle_display(text).split('\n'))
