-- ServerScriptService > DataStoreScript
local DSS = game:GetService("DataStoreService")
local store = DSS:GetDataStore("PlayerData_v1")

game.Players.PlayerAdded:Connect(function(player)
	local key = "Player_" .. player.UserId
	local success, data = pcall(function()
		return store:GetAsync(key)
	end)
	if success and data then
		player.leaderstats.Cash.Value = data.Cash or 0
		player.leaderstats.Rebirth.Value = data.Rebirth or 0
	end
end)

game.Players.PlayerRemoving:Connect(function(player)
	local key = "Player_" .. player.UserId
	pcall(function()
		store:SetAsync(key, {
			Cash = player.leaderstats.Cash.Value,
			Rebirth = player.leaderstats.Rebirth.Value,
		})
	end)
end)

game:BindToClose(function()
	for _, player in ipairs(game.Players:GetPlayers()) do
		local key = "Player_" .. player.UserId
		pcall(function()
			store:SetAsync(key, {
				Cash = player.leaderstats.Cash.Value,
				Rebirth = player.leaderstats.Rebirth.Value,
			})
		end)
	end
end)
