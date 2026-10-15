-- Synthetic syntax fixture; Class and entity APIs are not implemented here.
local function oncount(self, value, old)
    if self.inst.replica.meter ~= nil then
        self.inst.replica.meter:SetValue(value)
    end
end

local Meter = Class(function(self, inst)
    self.inst = inst
    self.count = 3
    self.callback = nil
    -- self.fake = 99
end, nil, { count = oncount })

function Meter:Use(amount, ...)
    if amount == nil then
        return false
    end
    if self.inst.components.helper ~= nil then
        self.inst.components.helper:Apply(amount)
    else
        self.count = self.count - amount
    end
    if self.callback ~= nil then
        self.callback(self.inst, amount, ...)
    end
    self.inst:PushEvent("meterchanged", { value = self.count })
    self.inst:ListenForEvent("tick", oncount, self.inst)
    self.inst:RemoveComponent("helper")
    return true, self.count
end

function Meter:Close()
    self.inst:RemoveTag("open")
end

Meter.OnRemoveFromEntity = Meter.Close
--[[ function Meter:Imaginary() self.phantom = 1 end ]]
return Meter
