-- Direct names and parameterized registrations must remain distinct.
local function factory()
    local inst = CreateEntity()
    if not TheWorld.ismastersim then
        return inst
    end
    inst:AddComponent("meter")
    return inst
end

local function MakeNamed(name)
    return Prefab(name, factory)
end

return Prefab("demo_a", factory),
    Prefab("demo_b", factory),
    MakeNamed("demo_c")
