'use strict';
'require view';
'require fs';
'require ui';
'require poll';

var helper = '/usr/bin/gl-bluetooth-web';

function parseResult(res) {
	if (!res || res.code !== 0)
		throw new Error((res && res.stderr) || 'Bluetooth command failed');

	try {
		return JSON.parse(res.stdout || '{}');
	}
	catch (e) {
		throw new Error('Invalid response from Bluetooth service');
	}
}

return view.extend({
	loadStatus: function() {
		return fs.exec(helper, [ 'status' ]).then(parseResult);
	},

	load: function() {
		return this.loadStatus();
	},

	setValue: function(id, text, good) {
		var node = document.getElementById(id);
		if (!node)
			return;
		node.textContent = text;
		node.style.fontWeight = 'bold';
		node.style.color = good ? '#2e8b57' : '#c0392b';
	},

	updateStatus: function(data) {
		this.setValue('bt-running', data.running ? 'ACTIF' : 'ARRÊTÉ', data.running);
		this.setValue('bt-enabled', data.enabled ? 'OUI' : 'NON', data.enabled);
		this.setValue('bt-bonded', data.bonded ? 'APPAIRÉ' : 'NON APPAIRÉ', data.bonded);
		this.setValue('bt-connected', data.connected ? 'CONNECTÉ' : 'DÉCONNECTÉ', data.connected);

		var name = document.getElementById('bt-name');
		if (name)
			name.textContent = data.name || 'GL-E5800';
	},

	handleAction: function(action, ev) {
		var labels = {
			start: 'Démarrage du Bluetooth…',
			stop: 'Arrêt du Bluetooth…',
			restart: 'Redémarrage du Bluetooth…',
			reconnect: 'Reconnexion GATT LE puis HID…',
			'pair-keyboard': 'Appairage du clavier…',
			scan: 'Recherche des appareils pendant 15 secondes…'
		};

		ui.showModal('Bluetooth', [
			E('p', { 'class': 'spinning' }, labels[action] || 'Action en cours…')
		]);

		return fs.exec(helper, [ action ]).then(parseResult).then(L.bind(function(data) {
			ui.hideModal();

			if (!data.ok)
				throw new Error(data.error || 'Bluetooth action failed');

			if (data.scan_count != null) {
				ui.addNotification(null, E('p', {},
					'%d appareil(s) Bluetooth détecté(s).'.format(data.scan_count)));
				return this.loadStatus().then(L.bind(this.updateStatus, this));
			}

			this.updateStatus(data);
			ui.addNotification(null, E('p', {}, 'Action Bluetooth terminée.'));
		}, this)).catch(L.bind(function(err) {
			ui.hideModal();
			ui.addNotification(null, E('p', {}, err.message || String(err)));
		}, this));
	},

	render: function(data) {
		var table = E('table', { 'class': 'table' }, [
			E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left', 'width': '45%' }, 'Service Bluetooth'), E('td', { 'class': 'td left', 'id': 'bt-running' }) ]),
			E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left' }, 'Activation au démarrage'), E('td', { 'class': 'td left', 'id': 'bt-enabled' }) ]),
			E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left' }, 'Nom du routeur'), E('td', { 'class': 'td left', 'id': 'bt-name' }) ]),
			E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left' }, 'Périphérique HID configuré'), E('td', { 'class': 'td left', 'id': 'bt-bonded' }) ]),
			E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left' }, 'Connexion HID'), E('td', { 'class': 'td left', 'id': 'bt-connected' }) ])
		]);

		var buttons = E('div', { 'class': 'cbi-page-actions' }, [
			E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, 'handleAction', 'start') }, 'Démarrer'),
			' ',
			E('button', { 'class': 'btn cbi-button-neutral', 'click': ui.createHandlerFn(this, 'handleAction', 'restart') }, 'Redémarrer'),
			' ',
			E('button', { 'class': 'btn cbi-button-negative', 'click': ui.createHandlerFn(this, 'handleAction', 'stop') }, 'Arrêter')
		]);

		var deviceButtons = E('div', { 'class': 'cbi-page-actions' }, [
			E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, 'handleAction', 'reconnect') }, 'Reconnecter le clavier'),
			' ',
			E('button', { 'class': 'btn cbi-button-positive', 'click': ui.createHandlerFn(this, 'handleAction', 'pair-keyboard') }, 'Appairer le clavier'),
			' ',
			E('button', { 'class': 'btn cbi-button-neutral', 'click': ui.createHandlerFn(this, 'handleAction', 'scan') }, 'Scanner')
		]);

		var root = E([], [
			E('h2', {}, 'Bluetooth'),
			E('div', { 'class': 'cbi-map-descr' },
				'Gestion de la puce Qualcomm WCN7850 intégrée au GL-E5800.'),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'État'),
				table,
				buttons
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'Clavier Bluetooth'),
				E('p', {}, 'Réveillez ou sélectionnez le canal Bluetooth du périphérique, puis cliquez sur « Reconnecter ».'),
				E('p', {}, 'Pour appairer, placez d’abord le périphérique en mode pairing puis lancez immédiatement l’action.'),
				deviceButtons
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'À propos'),
				E('p', {}, 'La pile Qualcomm reçoit les frappes HID. Elle ne crée pas encore de périphérique Linux /dev/input ; un pont uinput sera nécessaire pour piloter les applications écran.')
			])
		]);

		window.setTimeout(L.bind(this.updateStatus, this, data), 0);
		poll.add(L.bind(function() {
			return this.loadStatus().then(L.bind(this.updateStatus, this));
		}, this), 5);

		return root;
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
