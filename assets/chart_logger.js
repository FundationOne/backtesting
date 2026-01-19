(function () {
  'use strict';

  var TARGET_ID = 'main-portfolio-chart-v2';
  var POLL_MS = 500;
  var lastSignature = null;

  function isFiniteNumber(v) {
    return typeof v === 'number' && isFinite(v);
  }

  function isArrayLike(v) {
    return v != null && typeof v !== 'string' && typeof v.length === 'number';
  }

  function isBinaryArrayObject(v) {
    return v && typeof v === 'object' && typeof v.bdata === 'string' && typeof v.dtype === 'string';
  }

  function base64ToArrayBuffer(b64) {
    var binary = atob(b64);
    var len = binary.length;
    var bytes = new Uint8Array(len);
    for (var i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }

  function decodeBinaryArrayObject(v) {
    // Dash/Plotly sometimes serializes numpy arrays as {dtype, bdata, shape}
    // dtype examples: 'f8' (float64), 'f4' (float32), 'i4' (int32), 'i2' (int16)
    try {
      if (!isBinaryArrayObject(v)) return null;
      var buf = base64ToArrayBuffer(v.bdata);
      switch (v.dtype) {
        case 'f8': return new Float64Array(buf);
        case 'f4': return new Float32Array(buf);
        case 'i4': return new Int32Array(buf);
        case 'i2': return new Int16Array(buf);
        case 'u4': return new Uint32Array(buf);
        case 'u2': return new Uint16Array(buf);
        case 'u1': return new Uint8Array(buf);
        default:
          // Unknown dtype; return bytes so we still get a length.
          return new Uint8Array(buf);
      }
    } catch (e) {
      return null;
    }
  }

  function getSeries(t) {
    if (!t) return [];
    var y = t.y;
    // Plotly may store typed arrays (Float64Array, etc). They are not Array.isArray.
    if (isArrayLike(y)) return y;
    // Or it may store binary-encoded arrays as objects.
    if (isBinaryArrayObject(y)) {
      var decoded = decodeBinaryArrayObject(y);
      if (decoded && isArrayLike(decoded)) return decoded;
    }
    return [];
  }

  function summarizeTrace(t) {
    t = t || {};
    var y = getSeries(t);
    var yLen = y && typeof y.length === 'number' ? y.length : 0;
    var firstY = yLen ? y[0] : null;
    var lastY = yLen ? y[yLen - 1] : null;

    var minY = null;
    var maxY = null;
    for (var i = 0; i < yLen; i++) {
      var v = y[i];
      if (!isFiniteNumber(v)) {
        if (v == null) continue;
        v = Number(v);
      }
      if (!isFiniteNumber(v)) continue;
      if (minY === null || v < minY) minY = v;
      if (maxY === null || v > maxY) maxY = v;
    }

    return {
      name: t.name,
      n: yLen,
      first_y: firstY,
      last_y: lastY,
      min_y: minY,
      max_y: maxY,
      y_type: yLen ? typeof y[yLen - 1] : null,
      y_container_type: (t.y == null) ? null : (Object.prototype.toString.call(t.y)),
      y_object_keys: (t.y && typeof t.y === 'object' && !isArrayLike(t.y)) ? Object.keys(t.y).slice(0, 10) : null
    };
  }

  function signatureFromTraces(traces) {
    try {
      if (!traces || !traces.length) return 'empty';
      // Keep signature cheap: names + last_y (stringified) + lengths.
      var parts = [];
      for (var i = 0; i < traces.length; i++) {
        var t = traces[i] || {};
        var y = getSeries(t);
        var yLen = y && typeof y.length === 'number' ? y.length : 0;
        var lastY = yLen ? y[yLen - 1] : null;
        parts.push(String(t.name || ''));
        parts.push(String(yLen));
        parts.push(String(lastY));
      }
      return parts.join('|');
    } catch (e) {
      return 'sig_error';
    }
  }

  function logFromGraphDiv(gd) {
    try {
      var figData = (gd && gd.data) ? gd.data : [];
      var sig = signatureFromTraces(figData);
      if (sig === lastSignature) return;
      lastSignature = sig;

      var summaries = [];
      for (var i = 0; i < figData.length; i++) summaries.push(summarizeTrace(figData[i]));

      console.groupCollapsed('[ChartAsset] main-portfolio-chart updated');
      console.log('[ChartAsset] fired @', new Date().toISOString());
      if (gd && gd.layout) {
        console.log('[ChartAsset] layout:', {
          title: gd.layout.title,
          yaxis: gd.layout.yaxis,
          xaxis: gd.layout.xaxis
        });
      }
      if (console.table) console.table(summaries);
      else console.log('[ChartAsset] traces:', summaries);

      // If Plotly has richer data elsewhere, surface it too.
      try {
        if (gd && gd._fullData && gd._fullData.length) {
          var fullSummaries = [];
          for (var k = 0; k < gd._fullData.length; k++) fullSummaries.push(summarizeTrace(gd._fullData[k]));
          if (console.table) {
            console.log('[ChartAsset] _fullData:');
            console.table(fullSummaries);
          } else {
            console.log('[ChartAsset] _fullData:', fullSummaries);
          }
        }
      } catch (e2) {
        console.log('[ChartAsset] _fullData log failed:', e2);
      }
      console.groupEnd();
    } catch (e) {
      console.error('[ChartAsset] Failed to log figure:', e);
    }
  }

  function tryAttach() {
    var container = document.getElementById(TARGET_ID);
    if (!container) return false;

    var plots = container.getElementsByClassName('js-plotly-plot');
    var gd = plots && plots.length ? plots[0] : null;
    if (!gd) return false;

    if (gd.__chartLoggerAttached) return true;
    gd.__chartLoggerAttached = true;

    // Log immediately if data exists
    logFromGraphDiv(gd);

    // Attach Plotly events
    if (typeof gd.on === 'function') {
      gd.on('plotly_afterplot', function () { logFromGraphDiv(gd); });
      gd.on('plotly_relayout', function () { logFromGraphDiv(gd); });
      gd.on('plotly_redraw', function () { logFromGraphDiv(gd); });
    }

    console.log('[ChartAsset] Attached logger to', TARGET_ID);
    return true;
  }

  // Poll until the graph exists (Dash mounts it asynchronously)
  setInterval(function () {
    tryAttach();
  }, POLL_MS);
})();
