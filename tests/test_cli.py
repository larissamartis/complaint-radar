from complaint_radar.contracts.checker import default_contract_path, load_contract


def test_default_contract_ships_inside_package():
    path = default_contract_path()
    assert "complaint_radar" in path.parts
    assert load_contract(path)["name"] == "complaints"
