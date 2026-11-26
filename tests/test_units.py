import pytest

from app.services import estimation as E
from app.services import measurements as M
from app.services import procurement as P
from app.services import scheduling as S


def test_conversion():
    assert M.convert(12, "ft", "in") == pytest.approx(144)
    assert M.convert(1, "sqm", "sqft") == pytest.approx(10.7639, rel=1e-4)
    with pytest.raises(ValueError):
        M.convert(1, "ft", "kg")
    with pytest.raises(ValueError):
        M.convert(-1, "ft", "m")


def test_room_geometry():
    g = M.room_geometry(12, 15, 10, "ft", [{"width": 3, "height": 7, "count": 1}])
    assert g["floor_area_sqft"] == 180 and g["gross_wall_area_sqft"] == 540 and g["net_wall_area_sqft"] == 519
    with pytest.raises(ValueError):
        M.room_geometry(12, 15, 10, "ft", [{"width": 100, "height": 100}])


def test_tiles_paint_bricks():
    assert E.tiles(180, 24, 24, "in")["final_quantity"] == 50
    assert E.paint(400, 2, 100)["final_quantity"] == 8.4
    assert E.bricks(10 * 10.7639104167)["final_quantity"] == 525
    with pytest.raises(ValueError):
        E.run("paint", {"area_sqft": 400, "coats": 2})  # coverage is mandatory - never defaulted
    with pytest.raises(ValueError):
        E.tiles(-5, 12, 12)


def test_critical_path_and_cycle():
    r = S.critical_path([{"id": 1, "duration": 3, "deps": []}, {"id": 2, "duration": 2, "deps": [1]},
                         {"id": 3, "duration": 5, "deps": [1]}, {"id": 4, "duration": 1, "deps": [2, 3]}])
    assert r["total_duration_days"] == 9 and r["critical_path"] == [1, 3, 4]
    with pytest.raises(ValueError):
        S.critical_path([{"id": 1, "duration": 1, "deps": [2]}, {"id": 2, "duration": 1, "deps": [1]}])


def test_procurement():
    assert P.purchase_requirement(15, 0, 5, 0) == 10
    assert P.purchase_requirement(5, 0, 20, 0) == 0
    c = P.delivered_cost(400, 18, 500, 10, 4)   # MOQ forces 10 bags
    assert c["buy_quantity"] == 10 and c["total"] == 5220.0
