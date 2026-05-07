from polydocbench.layout.bbox import BBoxCalculator
from polydocbench.layout.handlers import GraphicPlacementHandler, HeadingPlacementHandler, TextPlacementHandler
from polydocbench.layout.placement import PlacementEngine


def test_placement_engine_dispatches_element_handlers():
    engine = PlacementEngine(BBoxCalculator())

    assert isinstance(engine._get_handler("paragraph"), TextPlacementHandler)
    assert isinstance(engine._get_handler("heading2"), HeadingPlacementHandler)
    assert isinstance(engine._get_handler("image"), GraphicPlacementHandler)
    assert isinstance(engine._get_handler("unknown"), TextPlacementHandler)
