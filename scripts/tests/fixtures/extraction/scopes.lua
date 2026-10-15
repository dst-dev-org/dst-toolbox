-- Same names in separate scopes and indirect targets are deliberate.
local function first()
    local function update(value)
        return value
    end
    return update(1)
end

local function second(inst, name, event, callback)
    local function update(value)
        return value * 2
    end
    local function holder()
        return function(value)
            return value + 1
        end
    end
    inst.components[name]:Apply(update(2))
    inst:PushEvent(event, nil)
    inst:ListenForEvent(event, callback)
    local quoted = "inst:AddComponent('fake')"
    return quoted, holder()
end

return first, second
