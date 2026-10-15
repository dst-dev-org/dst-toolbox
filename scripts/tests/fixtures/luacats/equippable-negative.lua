---@param component component_equippable
local function probe(component)
    component.walkspeedmult = "bad" -- expect assign-type-mismatch
    component.equipslot = 1 -- expect assign-type-mismatch: slot name, not network ID
    component:SetOnPocket(42) -- expect param-type-mismatch
    component:IsRestricted(nil) -- expect param-type-mismatch
    component:OnSave() -- expect undefined-field: no inherited editor hook
    component:SetOnPocket(function(item, owner) owner:IsValid() end) -- expect need-check-nil
end

return probe
