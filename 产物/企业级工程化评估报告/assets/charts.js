/* 企业级工程化评估报告 — 图表逻辑（颜色全部派生自主题 CSS 变量） */
(function () {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var good = style.getPropertyValue('--good').trim();
  var warn = style.getPropertyValue('--warn').trim();
  var bad = style.getPropertyValue('--bad').trim();

  function scoreColor(v) {
    if (v >= 8) return good;
    if (v >= 5) return warn;
    return bad;
  }

  var dims = [
    { name: '后端架构与分层设计', value: 9.0 },
    { name: '数据模型与迁移管理', value: 6.0 },
    { name: '安全与合规', value: 6.0 },
    { name: '测试体系与质量门禁', value: 5.0 },
    { name: '前端工程化', value: 5.0 },
    { name: '性能与伸缩性', value: 5.0 },
    { name: '容器化与部署编排', value: 4.0 },
    { name: '可观测性', value: 4.0 },
    { name: '文档与协作治理', value: 4.0 },
    { name: '配置与密钥管理', value: 3.0 },
    { name: '依赖锁定与可复现构建', value: 2.0 },
    { name: 'CI/CD 流水线', value: 1.0 }
  ];

  var avg = (dims.reduce(function (s, d) { return s + d.value; }, 0) / dims.length).toFixed(2);

  var chart = echarts.init(document.getElementById('chart-score'), null, { renderer: 'svg' });
  chart.setOption({
    animation: false,
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      formatter: function (p) {
        return p.name + '<br/>得分：' + p.value.toFixed(1) + ' / 10';
      }
    },
    grid: { left: 8, right: 90, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      max: 10,
      axisLine: { lineStyle: { color: rule } },
      axisLabel: { color: muted, fontFamily: 'JetBrainsMono' },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } }
    },
    yAxis: {
      type: 'category',
      data: dims.map(function (d) { return d.name; }),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: ink, fontSize: 13, width: 200, overflow: 'truncate' }
    },
    series: [{
      type: 'bar',
      data: dims.map(function (d) {
        return {
          value: d.value,
          itemStyle: { color: scoreColor(d.value), borderRadius: [0, 6, 6, 0] },
          label: {
            show: true,
            position: 'right',
            formatter: function (p) { return p.value.toFixed(1); },
            color: scoreColor(d.value),
            fontFamily: 'JetBrainsMono',
            fontWeight: 700,
            fontSize: 13
          }
        };
      }),
      barWidth: 22,
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: accent, type: 'dashed', width: 1.4 },
        label: {
          show: true,
          position: 'end',
          formatter: '均值 ' + avg,
          color: accent,
          fontSize: 11,
          fontFamily: 'JetBrainsMono'
        },
        data: [{ xAxis: avg }]
      }
    }]
  });
  window.addEventListener('resize', function () { chart.resize(); });
})();
