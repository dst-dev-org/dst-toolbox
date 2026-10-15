-- SPDX-License-Identifier: AGPL-3.0-or-later

local game = GLOBAL
local load_prefab_file = game.LoadPrefabFile
local origins = game.setmetatable({}, { __mode = "k" })

-- Key by the actual definition so a later registration of the same name
-- cannot inherit a previous definition's file.
game.LoadPrefabFile = function(filename, async_validation, asset_path)
    local definitions = load_prefab_file(filename, async_validation, asset_path)
    if type(definitions) ~= "table" then
        return definitions
    end
    local source_file = filename:gsub("\\", "/")
    if source_file:sub(-4) ~= ".lua" then
        source_file = source_file .. ".lua"
    end
    for _, definition in ipairs(definitions) do
        if type(definition) == "table" and game.Prefabs[definition.name] == definition then
            origins[definition] = { source_file = source_file, mod_root = asset_path }
        end
    end
    return definitions
end

local function catalog_kind(name, prefab, has_factory, scrapbook_type)
    if prefab.is_skin then
        return "skin"
    elseif not has_factory then
        return "no_lua_factory"
    elseif name:sub(-7) == "_placer" then
        return "placer_hint"
    elseif name:sub(-11) == "_classified" then
        return "classified_hint"
    end
    return scrapbook_type or "uncategorized"
end

game.rawset(game, "c_prefab_catalog", function(steam_build_id)
    local world = game.TheWorld
    if world == nil or not world.ismastersim then
        print("[Prefab Catalog] Run from the server console in a loaded world.")
        return
    end
    if steam_build_id ~= nil and (type(steam_build_id) ~= "string" or not steam_build_id:match("^%d+$")) then
        print('[Prefab Catalog] Optional Steam build ID must be a quoted numeric string.')
        return
    end

    local scrapbook = require("screens/redux/scrapbookdata")
    local entries = {}
    for name, prefab in pairs(game.Prefabs) do
        local origin = origins[prefab]
        local scrapbook_entry = scrapbook[name]
        local scrapbook_type = scrapbook_entry and scrapbook_entry.type
        local has_factory = type(prefab.fn) == "function"
        local factory_info = has_factory and game.debug.getinfo(prefab.fn, "S")
        local name_key = name:upper()
        local name_table_value = game.STRINGS.NAMES[name_key]
        entries[#entries + 1] = {
            name = name,
            status = "confirmed",
            kind = catalog_kind(name, prefab, has_factory, scrapbook_type),
            has_lua_factory = has_factory,
            source_file = origin and origin.source_file or nil,
            mod_root = origin and origin.mod_root or nil,
            factory_source = factory_info and factory_info.source or nil,
            scrapbook_type = scrapbook_type,
            strings_name = type(name_table_value) == "string" and name_table_value or nil,
        }
    end
    table.sort(entries, function(left, right) return left.name < right.name end)

    local shard_id = tostring(game.TheShard:GetShardId())
    local filename = "dst-wiki-prefabs-" .. shard_id:gsub("[^%w_-]", "_") .. ".json"
    local payload = game.json.encode_compliant({
        snapshot = steam_build_id,
        game_version = tostring(game.APP_VERSION),
        world = world.worldprefab or world.prefab,
        shard = shard_id,
        enabled_mods = game.ModManager:GetEnabledModNames(),
        entries = entries,
    })
    game.TheSim:SetPersistentString(filename, payload, false, function()
        game.TheSim:GetPersistentString(filename, function(success, saved)
            if success and saved == payload then
                print(string.format("[Prefab Catalog] Saved %d registrations to %s", #entries, filename))
            else
                print("[Prefab Catalog] Could not verify the saved file: " .. filename)
            end
        end)
    end)
end)
