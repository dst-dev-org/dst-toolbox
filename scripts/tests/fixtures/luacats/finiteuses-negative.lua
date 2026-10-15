---@param component component_finiteuses
local function probe(component)
    component:SetMaxUses("bad") -- expect param-type-mismatch
    component:OnLoad(nil) -- expect param-type-mismatch
    component:OnUpdate(1) -- expect undefined-field: no runtime/editor base inheritance
end

return probe
