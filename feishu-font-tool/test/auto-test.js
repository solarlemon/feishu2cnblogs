(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(2900);
  const host = document.getElementById('fft-ui-host');
  const sr = host && host.shadowRoot;
  const result = {
    host: Boolean(host),
    body: getComputedStyle(document.getElementById('p1')).fontSize,
    h2: getComputedStyle(document.getElementById('h2')).fontSize,
    rootClass: document.documentElement.className,
    fontValue: sr ? sr.getElementById('fft-font').value : null,
    sizeValue: sr ? sr.getElementById('fft-size').value : null,
    autoChecked: sr ? sr.getElementById('fft-auto').checked : null,
    status: sr ? sr.getElementById('fft-status').textContent : null
  };
  result.ok = result.body === '20px' && result.h2 === '27.5px' &&
    /fft-font-on/.test(result.rootClass) && /fft-size-on/.test(result.rootClass) &&
    result.fontValue === 'simsun' && result.sizeValue === '20' && result.autoChecked === true;
  return JSON.stringify(result);
})()
