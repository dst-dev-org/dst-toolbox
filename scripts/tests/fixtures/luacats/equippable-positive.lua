---@param component component_equippable
---@param owner ent
local function probe(component, owner)
    component.equipslot = "hands"
    component.walkspeedmult = 1.30
    component.walkspeedmult = nil
    component.restrictedtag = nil
    component:SetOnEquip(function(item, wearer, from_ground)
        item:IsValid()
        wearer:IsValid()
        if from_ground then item:IsValid() end
    end)
    component:SetOnPocket(function(item, wearer)
        item:IsValid()
        if wearer ~= nil then wearer:IsValid() end
    end)
    component:SetOnUnequip(function(item, wearer)
        item:IsValid()
        wearer:IsValid()
    end)
    component:SetOnEquipToModel(function(item, wearer)
        item:IsValid()
        wearer:IsValid()
    end)
    component:SetDappernessFn(function(item, wearer)
        item:IsValid()
        if wearer ~= nil then wearer:IsValid() end
        return 3 / 60
    end)
    component:SetOnPocket(nil)
    component:SetOnUnequip()
    component:SetDappernessFn(nil)
    component:ToPocket()
    component:ToPocket(nil)
    component:Equip(owner)
    component:Unequip(owner)
    component:SetPreventUnequipping(true)
    component:SetPreventUnequipping()
    ---@type number
    local rate = component:GetDapperness()
    ---@type boolean
    local restricted = component:IsRestricted(owner)
    ---@type number
    local moisture = component:GetEquippedMoisture().moisture
    return rate, restricted, moisture
end

return probe
