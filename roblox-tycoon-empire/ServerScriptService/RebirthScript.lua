-- ServerScriptService > RebirthScript
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local rebirthEvent = Instance.new("RemoteEvent")
rebirthEvent.Name = "RebirthEvent"
rebirthEvent.Parent = ReplicatedStorage

local REBIRTH_COST = 10000
local MULTIPLIERS = { 1.5, 2, 2.5, 3, 5 }

rebirthEvent.OnServerEvent:Connect(function(player)
	local cash = player.leaderstats.Cash
	local rebirth = player.leaderstats.Rebirth
	if cash.Value >= REBIRTH_COST then
		rebirth.Value = rebirth.Value + 1
		cash.Value = 100
	end
end)

function getMultiplier(rebirthCount)
	if rebirthCount >= 5 then return 5 end
	if rebirthCount >= 2 then return 2 end
	if rebirthCount >= 1 then return 1.5 end
	return 1
end
