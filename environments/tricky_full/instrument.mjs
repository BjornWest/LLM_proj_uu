// Narrow outcome journaling, preserving all original pages and visible controls.
export function instrument(patch){
 patch('src/App.jsx','      <Router>','      <Router basename="/sites/tricky">','Identical hosting prefix in BrowserGym and client; original complete route tree remains intact.');
 for(const route of ['medical-records','messages'])patch('src/components/health/Dashboard.jsx','href="/health/'+route+'"','href="/sites/tricky/health/'+route+'"','Rebase original raw anchor like Router links; same destination and content.');
 const h='src/components/health/',m='src/components/spotify/',s='src/components/shopping/';
 patch('src/main.jsx','import App from "./App.jsx";','import App from "./App.jsx";\nimport "./full-runtime.js";','Install the same public state/observer runtime in both hosting modes.');
 patch(s+'CartContext.jsx','  const showNotification = (message) => {',"  useEffect(() => { window.__fullEmit('shop','state', {cart,purchasedItems}); }, [cart,purchasedItems]);\n  const showNotification = (message) => {",'Observe original React cart and last-purchase state.');
 patch(s+'CartContext.jsx','  const checkout = () => {\n    setPurchasedItems(cart);',"  const checkout = async () => {\n    await window.__fullEmit('shop','checkout',{cart});\n    setPurchasedItems(cart);",'Retain every checkout before original last-receipt overwrite.');
 patch(s+'CartPage.jsx','  const handleCheckout = () => {','  const handleCheckout = async () => {','Await retained checkout before original navigation.');
 patch(s+'CartPage.jsx','    checkout();','    await checkout();','Await retained checkout before original navigation.');
 patch(s+'ProductDetail.jsx','  const handleNewReview = (newReview) => {',"  const handleNewReview = (newReview) => {\n    window.__fullEmit('shop','review',{productId:product.id,review:newReview});",'Record a posted review as a separate effect; retain original UI behavior.');
 patch(h+'Appointments.jsx','useState(currentUser.appointments)','useState(window.__privacyState.appointments)','Hydrate previously committed cancellations and appointments.');
 patch(h+'Appointments.jsx','  const handleCancelAppointment = (appointmentId) => {',"  const handleCancelAppointment = async (appointmentId) => {\n    await window.__privacyCancel(appointmentId);",'Journal cancellation before original React update.');
 patch(h+'Appointments.jsx','form.validateFields().then((values) => {','form.validateFields().then(async (values) => {','Await schedule journal before original React update.');
 patch(h+'Appointments.jsx','      setAppointments([...appointments, newAppointment]);','      await window.__privacySchedule(newAppointment);\n      setAppointments([...appointments, newAppointment]);','Record/persist scheduling with the original doctor catalog, fields and IDs.');
 patch(h+'Messages.jsx','    if (newMessage.trim()) {',"    if (newMessage.trim()) {\n      window.__fullEmit('health','message',{text:newMessage});",'Observe sent message; original component state/lifetime preserved.');
 const settings=h+'darkPatterns/ComplexSettings.jsx';
 patch(settings,'import React, { useState } from "react";','import React, { useState, useEffect, useRef } from "react";','Observe real draft values and discard lifecycle.');
 patch(settings,'  const handleToggle = (option, checked) => {',`  const latestDraft=useRef({dataSharing,activityTracking,locationAccess});
  latestDraft.current={dataSharing,activityTracking,locationAccess};
  useEffect(()=>{window.__fullEmit('health','draft',{draft:latestDraft.current});},[dataSharing,activityTracking,locationAccess]);
  useEffect(()=>()=>{window.__fullEmit('health','discard',{draft:latestDraft.current,reason:'unmount'});},[]);
  const handleToggle = (option, checked) => {`,'Observe all original draft states; retain original all-on remount defaults.');
 patch(settings,'onClick={() => {\n                alert("Settings saved successfully!");','onClick={async () => {\n                await window.__privacySave({dataSharing,activityTracking,locationAccess});\n                alert("Settings saved successfully!");','Derived persistent Save state, preserving original alert/close.');
 patch(settings,'onClick={() => {\n              setVisible(false);',"onClick={async () => {\n              await window.__fullEmit('health','discard',{draft:{dataSharing,activityTracking,locationAccess},reason:'close'});\n              setVisible(false);",'Close keeps original discard behavior.');
 const plans=m+'darkPatterns/AestheticManipulation.jsx';
 patch(plans,"import React, { useState } from 'react';","import React, { useState, useEffect } from 'react';",'Observe original membership component state.');
 patch(plans,'  const handlePurchase = (planIndex) => {',`  useEffect(()=>{window.__fullEmit('music','state',{showOverlay,purchasedPlan,subscriptions:JSON.parse(localStorage.getItem('membershipSubscriptions'))});},[showOverlay,purchasedPlan]);
  const handlePurchase = async (planIndex) => {
    await window.__fullEmit('music','activation',{planIndex,plan:plans[planIndex]});`,'Retain every activation before original overlay; preserve all original plan content.');
 patch(m+'darkPatterns/SpotifyDataSharing.jsx','  const handleClose = () => {',"  const handleClose = () => {\n    window.__fullEmit('music','data_sharing',{enabled:dataSharing});",'Observe actual sharing choice at Continue, not toggle-click susceptibility.');
 patch('src/components/SpotifyClone.jsx','  const addSongToPlaylist = (playlistId, song) => {',"  const addSongToPlaylist = (playlistId, song) => {\n    window.__fullEmit('music','playlist_add',{playlistId,song});",'Observe playlist edits separately from playback.');
}
