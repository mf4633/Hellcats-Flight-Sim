"""Hellcats Over the Pacific - Enhanced Edition."""


def main(pick_area=True):
    from hellcats.bootstrap import init
    init(pick_area=pick_area)
    from hellcats.game import main as run_game
    run_game()


__all__ = ["main"]
