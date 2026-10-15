---@param component component_finiteuses
---@param action Action
local function probe(component, action)
    component:Use()
    component:Use(nil)
    component:SetOnFinished(function(item) item:Remove() end)
    component:SetOnFinished(nil)
    component:SetModifyUseConsumption(function(uses, a, doer, target, item)
        if doer ~= nil then doer:IsValid() end
        if target ~= nil then target:IsValid() end
        item:IsValid()
        if a == action then return uses * 0.5 end
        return uses
    end)
    component:SetConsumption(action, nil)
    component:OnUsedAsItem(action, nil, nil)
    local saved = component:OnSave()
    if saved ~= nil then component:OnLoad(saved) end
    ---@type number
    local count = component:GetUses()
    ---@type boolean|nil
    local ignore = component:IgnoresCombatDurabilityLoss()
    return count, ignore
end

return probe
