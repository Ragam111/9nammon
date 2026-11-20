-- Script inside Tycoon Button Part (floor button to buy upgrades)
local button = script.Parent
local price = button:FindFirstChild("Price").Value
local itemToUnlock = button:FindFirstChild("ItemName").Value
local debounce = false

button.Touched:Connect(function(hit)
	if debounce then return end
	local player = game.Players:GetPlayerFromCharacter(hit.Parent)
	if not player then return end
	if player.leaderstats.Cash.Value >= price then
		debounce = true
		player.leaderstats.Cash.Value = player.leaderstats.Cash.Value - price
		local model = workspace.HiddenItems:FindFirstChild(itemToUnlock)
		if model then
			model.Transparency = 0
			model.CanCollide = true
		end
		button:Destroy()
	end
end)
