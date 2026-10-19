-- Script inside Collector Part
local collector = script.Parent
local ownerValue = collector:FindFirstChild("Owner")

collector.Touched:Connect(function(hit)
	local val = hit:FindFirstChild("Value")
	if val then
		local ownerName = ownerValue.Value
		local player = game.Players:FindFirstChild(ownerName)
		if player then
			player.leaderstats.Cash.Value = player.leaderstats.Cash.Value + val.Value
		end
		hit:Destroy()
	end
end)
