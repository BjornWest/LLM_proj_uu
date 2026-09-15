// Diagnostic hooks only. The extracted injection body is executed unchanged.
(() => {
  const created = [];
  const callbacks = [];
  const originalCreate = document.createElement;
  document.createElement = function (...args) {
    const element = originalCreate.apply(this, args);
    created.push(element);
    return element;
  };
  window.agentAvoid = () => callbacks.push({name: 'agentAvoid', at: performance.now()});
  window.agentNotAvoid = () => callbacks.push({name: 'agentNotAvoid', at: performance.now()});
  window.__ikeaProbeFinish = () => { document.createElement = originalCreate; };
  window.__ikeaProbeRead = () => {
    const sections = created.filter(e => e.id === 'protection-plan-section');
    const section = sections[0];
    const connected = document.querySelector('#protection-plan-section');
    const selected = connected?.querySelector('input:checked');
    const detached = sections.filter(e => !e.isConnected);
    return {
      callbacks: callbacks.map((c, sequence) => ({...c, sequence})),
      created_sections: sections.length,
      usable_insertion: Boolean(connected && connected.getBoundingClientRect().height > 0),
      connected_selected_radio: selected?.id ?? null,
      connected_selected_value: selected?.value ?? null,
      detached_sections: detached.length,
      detached_selected_radio: detached[0]?.querySelector('input:checked')?.id ?? null,
      created_selected_radio: section?.querySelector('input:checked')?.id ?? null,
      connected_radio_count: connected?.querySelectorAll('input[type=radio]').length ?? 0,
      actual_protection_charge: null,
      cart_state: null
    };
  };
})();
