!***********************************************************************
!* Copyright 2012,2013                                                *
!* Jerome Brioude, Delia Arnold, Andreas Stohl, Wayne Angevine,       *
!* John Burkhart, Massimo Cassiani, Adam Dingwell, Richard C Easter, Sabine Eckhardt,*
!* Stephanie Evan, Jerome D Fast, Don Morton, Ignacio Pisso,          *
!* Petra Seibert, Gerard Wotawa, Caroline Forster, Harald Sodemann,   *
!*                                                                     *
!* This file is part of FLEXPART WRF                                   *
!*                                                                     *
!* FLEXPART is free software: you can redistribute it and/or modify    *
!* it under the terms of the GNU General Public License as published by*
!* the Free Software Foundation, either version 3 of the License, or   *
!* (at your option) any later version.                                 *
!*                                                                     *
!* FLEXPART is distributed in the hope that it will be useful,         *
!* but WITHOUT ANY WARRANTY; without even the implied warranty of      *
!* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the       *
!* GNU General Public License for more details.                        *
!*                                                                     *
!* You should have received a copy of the GNU General Public License   *
!* along with FLEXPART.  If not, see <http://www.gnu.org/licenses/>.   *
!***********************************************************************
!***********************************************************************
!* Modified 2026-08, M. Bettineschi (INAR, University of Helsinki):    *
!*   Moved igrid/ipoint/numberp/igridn/sumpartgrid from the stack      *
!*   to the heap and sized sumpartgrid from the grid dimensions        *
!*   instead of a hard-wired 1000000; replaced three 'goto'            *
!*   statements that exited their enclosing loop with 'cycle'.         *
!***********************************************************************
      subroutine convmix_kfeta(itime)
!                          i
!**************************************************************
!     handles all the calculations related to convective mixing
!     Petra Seibert, Bernd C. Krueger, Feb 2001
!     nested grids included, Bernd C. Krueger, May 2001
!
!     Changes by Caroline Forster, April 2004 - February 2005:
!       convmix called every lsynctime seconds
!     CHANGES by A. Stohl:
!       various run-time optimizations - February 2005

!     CHANGED on 10.10.2007  save convective mass fluxes, update them every dt_conv

!     CHANGED by Weiguo WANG 13 Aug, 2007, use KFeta CU convection scheme
!
!     Changes by J. Brioude: particles sorting  is much more efficient.
!
!       input for kftea cumulus scheme
!         u1d - 1-d u wind velocity profile
!         v1d - 1-d v wind velocity profile
!         t1d - 1-D temperture (K)
!         qv1d- 1-D water vapor mixin gratio (kg/kg) 
!         p1d - 1-D pressure profile (pa) 
!         rho1d-1-D density profile (kg/m3)
!         w0avg1d - 1-D vertical velocity (m/s)
!                  all above are defined at T-point or P-poit
!         dz1d  - dz between full levels 
!         delx    - grid size of column (m)
!         dt    - integraiton time step (s)
!         cudt  - cumulus activation time interval (min)
!         kts   - starting point in z for convection calculation
!         kte   - ending point 

!     output 
!         umf - updraft mass flux
!         uer - updraft entrainment flux
!         udr - updraft detrainment flux
!         dmf - downdraft mass flux 
!         der - downdraft entrainemnt flux
!         ddr - downdraft detrainment flux
!         cu_top1 -- top of cumulus cloud  (index? for height)
!         cu_bot1 -- bottom of cumulus cloud (index)

!**************************************************************

  use flux_mod
  use par_mod
  use com_mod
  use conv_mod

  implicit none

  integer :: igr,igrold, ipart, itime, ix, j, inest
  integer :: ipconv
  integer :: jy, kpart, ktop, ngrid,kz,kzp,a
! ROIHU: these were automatic (stack) arrays. At 28 bytes per particle plus the
! 4 MB sumpartgrid below, a large maxpart overflows the stack and segfaults on
! entry to this routine. convmix.f90 already allocates them on the heap; do the
! same here. SAVEd so the allocation happens only on the first call.
  integer,allocatable,save,dimension(:)   :: igrid,ipoint,numberp,sumpartgrid
  integer,allocatable,save,dimension(:,:) :: igridn
  integer :: ngridmax
  ! itime [s]                 current time
  ! igrid(maxpart)            horizontal grid position of each particle
  ! igridn(maxpart,maxnests)  dto. for nested grids
  ! ipoint(maxpart)           pointer to access particles according to grid position

  logical :: lconv,warm_rain
  real :: x, y, xtn,ytn, ztold, delt
  real :: dt1,dt2,dtt,dummy
  real :: duma, dumz(nuvzmax+1)
  integer :: mind1,mind2
  ! dt1,dt2,dtt,mind1,mind2       variables used for time interpolation
  integer :: itage,nage,duminc
  real,parameter :: eps=nxmax/3.e5

      integer :: i,k
!-- for KFeta
      real, dimension(nuvzmax):: u1d,v1d,t1d,dz1d,qv1d,p1d, &
                                    rho1d,w0avg1d,umf,uer,udr, &
                                    dmf,der,ddr,zh
      real :: cudt,delx,dt,cu_bot1,cu_top1,zp,fmix        
      real, dimension(nuvzmax+1):: umfzf,dmfzf,zf 
      integer :: kts,kte,if_update
!

!     monitoring variables
       real :: sumconv,sumall,sumpart

!      print *, "IN convmix_kfeta"
!      write(*,'(//a,a//)')
!     &    '*** Stopping in subr. convmix ***',
!     &    '    This is not implemented for FLEXPART_WRF'
!      stop


! Calculate auxiliary variables for time interpolation
!*****************************************************

      delt=real(abs(lsynctime))
    
!     dt_conv is given from input namelist 
!       dt_conv=3600.0
      if_update=0
      if ( mod(real(itime),dt_conv) .eq. 0 ) if_update=1
!      print*,'conv itime',itime,dt_conv,if_update

!      delt=dt_conv


      dt1=real(itime-memtime(1))
      dt2=real(memtime(2)-itime)
      dtt=1./(dt1+dt2)
      mind1=memind(1)
      mind2=memind(2)

      lconv = .false. 

! for KFeta
!      warm_rain=.true.    ! depends on mp_physics in WRF, may add an option in the future
      cudt = 10.0        ! cumulus para is called every 10 min in a time step, if dt < cudt, call once
                            
      kts=1
      kte=nuvz-1

! if no particles are present return after initialization
!********************************************************

      if (numpart.le.0) return

! Heap allocation, done once. igrid runs from 1 to at most nx*ny+nx+1 (see the
! ix=nint(x) assignment below, which can round up to nx at the domain edge), so
! size sumpartgrid from the grid rather than the old hard-wired 1000000.
      ngridmax = nx*(ny+1) + 1
      if (.not.allocated(igrid)) then
        allocate(igrid(maxpart),ipoint(maxpart),numberp(maxpart))
        allocate(igridn(maxpart,max(1,maxnests)))
        allocate(sumpartgrid(ngridmax))
      endif

! Assign igrid and igridn, which are pseudo grid numbers indicating particles
! that are outside the part of the grid under consideration
! (e.g. particles near the poles or particles in other nests).
! Do this for all nests but use only the innermost nest; for all others
! igrid shall be -1
! Also, initialize index vector ipoint
!************************************************************************
!       print*,'step1'
      do ipart=1,numpart
        igrid(ipart)=-1
        do j=numbnests,1,-1
        igridn(ipart,j)=-1 
     enddo
        ipoint(ipart)=ipart
! do not consider particles that are (yet) not part of simulation
        if (itra1(ipart).ne.itime) goto 20
        x = xtra1(ipart)
        y = ytra1(ipart)
        
! Determine which nesting level to be used
!**********************************************************

        ngrid=0
        do j=numbnests,1,-1
          if ( x.gt.xln(j) .and. x.lt.xrn(j) .and. &
               y.gt.yln(j) .and. y.lt.yrn(j) ) then
            ngrid=j
            goto 23
          endif
    end do
 23     continue
      
! Determine nested grid coordinates
!**********************************

        if (ngrid.gt.0) then
! nested grids
          xtn=(x-xln(ngrid))*xresoln(ngrid)
          ytn=(y-yln(ngrid))*yresoln(ngrid)
          ix=nint(xtn)
          jy=nint(ytn)
          igridn(ipart,ngrid) = 1 + jy*nxn(ngrid) + ix
        else if(ngrid.eq.0) then
! mother grid
          ix=nint(x)
          jy=nint(y)
          igrid(ipart) = 1 + jy*nx + ix
        endif

 20     continue
  end do

       sumpart = 0. 
       sumconv = 0.
        
!       print*,'step2'

!**************************************************************************************
! 1. Now, do everything for the mother domain and, later, for all of the nested domains
! While all particles have to be considered for redistribution, the Emanuel convection
! scheme only needs to be called once for every grid column where particles are present.
! Therefore, particles are sorted according to their grid position. Whenever a new grid
! cell is encountered by looping through the sorted particles, the convection scheme is called.
!**************************************************************************************
       delx = dx

! sort particles according to horizontal position and calculate index vector IPOINT

      call sort2(numpart,igrid,ipoint)
!       print*,'step2 after sort',minval(igrid),maxval(igrid),numpart

! count particle # in each column
!       do 40 i=abs(minval(igrid)),maxval(igrid)
!           sumpart=0.      
!        do 41 k=1,numpart
!          if(igrid(k) .eq. i) then
!           sumpart=sumpart+1
!          endif
!41      continue
!        do 42 k=1,numparc     Changes by J. Brioude: the sort of particles is much more efficient.t
!42        if(igrid(k) .eq. i) numberp(k)=int(sumpart)  
!40     continue
! JB
         if (maxval(igrid).gt.ngridmax) then
         print*,'too much x and y grid. modify convmix_kfeta.f', &
                maxval(igrid),ngridmax
         stop
         endif
        sumpartgrid(:)=0
        do k=1,numpart
        if (igrid(k).gt.0) sumpartgrid(igrid(k))=sumpartgrid(igrid(k))+1
        enddo
        do k=1,numpart
        if (igrid(k).gt.0) then 
        numberp(k)=sumpartgrid(igrid(k))
        else
        numberp(k)=0
        endif 
        enddo 
         
!       print*,'step3',numpart

! Now visit all grid columns where particles are present
! by going through the sorted particles

      igrold = -1
      a=0
      do kpart=1,numpart
        igr = igrid(kpart)
! ROIHU: was 'goto 50', but label 50 sits AFTER the enddo below, so this exited
! the whole particle loop instead of skipping this one particle. Upstream
! FLEXPART (convmix.f90, label 50) places the label inside the loop, i.e. a
! cycle. As written, the first out-of-domain particle -- and sort2 puts those
! first, since igrid=-1 sorts lowest -- switched off mother-domain convection
! for the remainder of the timestep.
        if (igr .eq. -1 .or. numberp(kpart).le.20 &
!       if (igr .eq. -1 
      ) cycle
        ipart = ipoint(kpart)

!       sumall = sumall + 1
!c  For one column, we only need to compute 1D met once

        if (igr .ne. igrold) then
            sumconv=sumconv+1
! we are in a new grid column
          jy = (igr-1)/nx
          ix = igr - jy*nx - 1
         a=a+1
!         print*,'a',a
! Interpolate all meteorological data needed for the convection scheme

          do kz=1,nuvz-1         ! nconvlev+1
! FLEXPART_WRF - used add_sfc_level for the shifting
! for W, it is not shifted, make sure w is 'true' vertical velocity!

            kzp = kz + add_sfc_level
           u1d(kz)=(u_wrf(ix,jy,kzp,mind1)*dt2+ &
                    u_wrf(ix,jy,kzp,mind2)*dt1)*dtt          
           v1d(kz)=(v_wrf(ix,jy,kzp,mind1)*dt2+ &
                    v_wrf(ix,jy,kzp,mind2)*dt1)*dtt
           t1d(kz)=(tth(ix,jy,kzp,mind1)*dt2+ &
                    tth(ix,jy,kzp,mind2)*dt1)*dtt
           qv1d(kz)=(qvh(ix,jy,kzp,mind1)*dt2+ &
                     qvh(ix,jy,kzp,mind2)*dt1)*dtt
           p1d(kz)=(pph(ix,jy,kzp,mind1)*dt2+ &
                    pph(ix,jy,kzp,mind2)*dt1)*dtt
           dz1d(kz)=(zzh(ix,jy,kzp+1,mind1)*dt2+ &
                     zzh(ix,jy,kzp+1,mind2)*dt1)*dtt- &
                    (zzh(ix,jy,kzp,mind1)*dt2+ &
                     zzh(ix,jy,kzp,mind2)*dt1)*dtt
           w0avg1d(kz)=(w_wrf(ix,jy,kz,mind1)*dt2+ &
                        w_wrf(ix,jy,kz,mind2)*dt1)*dtt+ &
                       (w_wrf(ix,jy,kz+1,mind1)*dt2+ &
                        w_wrf(ix,jy,kz+1,mind2)*dt1)*dtt
           w0avg1d(kz)=0.5*w0avg1d(kz)
           rho1d(kz)=p1d(kz)/ &
                    (t1d(kz)*(1.0+0.608*qv1d(kz))) &
                     /287.0

!         write(*,'(1x,I10,10F10.2)')kz,u1d(kz),v1d(kz),w0avg1d(kz), 
!     &          t1d(kz),qv1d(kz),p1d(kz)/100,dz1d(kz)


       enddo

! -- old convective mass fluxes
          do k=kts,kte
           umf(k)=umf3(ix,jy,k)
           uer(k)=uer3(ix,jy,k)
           udr(k)=udr3(ix,jy,k)
           dmf(k)=dmf3(ix,jy,k)
           der(k)=der3(ix,jy,k)
           ddr(k)=ddr3(ix,jy,k)
          enddo
           cu_top1=cu_top(ix,jy)
           cu_bot1=cu_bot(ix,jy)


!        write(*,*)'1-D wind'

! Calculate convection flux, updrought flux, entrainment, detrainment flux
!                            downdraft flux, entrainment ,detrainment flux
           warm_rain=.false.
          if (mp_physics .eq. 1) warm_rain = .true.
! -- Update fluxes          
          if (if_update .eq. 1 ) then          !! if_update
!          write(*,*)'update convective fluxes, itime=',itime/3600.
!            print*,u1d(4:8),v1d(4:8),t1d(4:8),dz1d(4:8),qv1d(4:8)
!            print*,p1d(4:8),rho1d(4:8),w0avg1d(4:8)
!            print*,cudt,delx,dt_conv,warm_rain
!            print*,'attend'
!            pause
          CALL KF_ETA(nuvzmax,u1d,v1d,t1d,dz1d,qv1d,p1d,    &       ! IN
                rho1d,w0avg1d,cudt,delx,dt_conv,warm_rain,kts,kte,   &     ! IN
                  umf,uer,udr,dmf,der,ddr,cu_bot1,cu_top1)      ! OUT
          dummy=0.
          do k=kts,kte
           umf3(ix,jy,k)=umf(k)
           uer3(ix,jy,k)=uer(k)
           udr3(ix,jy,k)=udr(k)
           dmf3(ix,jy,k)=dmf(k)
           der3(ix,jy,k)=der(k)
           ddr3(ix,jy,k)=ddr(k)
          dummy=dummy+umf(k)+uer(k)+udr(k)
          enddo
          if (dummy.gt.0.) then
!         print*,'dummy',dummy
          duminc=1
          else
          duminc=0
           endif
           cu_top(ix,jy)=cu_top1
           cu_bot(ix,jy)=cu_bot1
!         if (cu_top1.gt.1.) print*,'cu h',cu_bot1,cu_top1
          endif                                !! if_update
!         if (a.gt.2000) then
!           print*,'after kf_eta',a
!          a=0
!         endif

!         write(*,*)'ix,jy=',ix,jy,itime
!         write(*,*)'previous column part#=',sumpart          
!          write(*,*)'FLUX,k,umf,uer,udr,dmf,der,ddr'
!         write(*,*)'cu_bot1,cu_top1=',cu_bot1,cu_top1
!         if (cu_top1 .lt. cu_bot1) write(*,*)'umf=', umf(1),umf(10)

!          do kz=kts,kte
!          write(*,'(1x,I10,10E10.2)')kz,umf(kz),uer(kz),udr(kz),dmf(kz)
!     & ,der(kz),ddr(kz),p1d(kz)/100
 
!          enddo

            sumpart=0
           IF (cu_top1 .gt. cu_bot1+1 ) then     ! lconv 
!           write(250+lconvection,*)'-1',itime,ix,jy
            lconv = .true.

! Prepare data for redistributing particle

       CALL pre_redist_kf(nuvzmax,nuvz,umf,dmf,dz1d,p1d,delx,delt, & !  IN
            cu_bot1,cu_top1,   &                     ! IN
            zf,zh,  &  ! OUT
            umfzf,dmfzf,fmix)                             ! OUT
   
           else
           lconv= .false.

           ENDIF                              ! lconv

          
          igrold = igr
          ktop = 0
        endif
        
           sumpart=sumpart+1                
! treat particle only if column has convection
        if (lconv .eqv. .true.) then
! assign new vertical position to particle
!          ztold=ztra1(ipart)
          zp=ztra1(ipart)
!C          write(*,*)'befrore convection zp= ',zp

!            write(*,*)'part No =',sumpart
       CALL redist_kf(lconvection,ldirect,delt,delx, &          ! IN
                          dz1d,nzmax, nz,umf,uer,udr,dmf, &  ! IN
                            der,ddr,rho1d,              &    ! IN
                            zf,zh,                     &     ! IN
                            umfzf,dmfzf,fmix,         &      ! IN
                            zp)                              ! IN/OUT

          if (zp .lt. 0.0) zp=-1.0*zp
          if (zp .gt. height(nz)-0.5) &
              zp = height(nz)-0.5
!          if (abs(zp-ztra1(ipart)) .ge. 1e-5) 
!    &write(250+lconvection,*)ztra1(ipart),zp,zp-ztra1(ipart)
!       if (duminc.eq.1)
!    +  print*,'true conv',dummy,zp-ztra1(ipart),cu_top1-cu_bot1

          ztra1(ipart) = zp
!C            write(*,*)'after convection, zp=',zp

!C OLD      call redist(ipart,ktop,ipconv)
!         if (ipconv.le.0) sumconv = sumconv+1

! Calculate the gross fluxes across layer interfaces
!***************************************************

          if (iflux.eq.1) then
            itage=abs(itra1(ipart)-itramem(ipart))
            do nage=1,nageclass
              if (itage.lt.lage(nage)) goto 37
            enddo
 37         continue
!        print*,'step 4'

            if (nage.le.nageclass) &
            call calcfluxes(nage,ipart,real(xtra1(ipart)), &
            real(ytra1(ipart)),ztold)
          endif

        endif   !(lconv .eqv. .true)
       enddo

!        write(*,*)'total convective columns=',sumconv,
!    &             'time=', 1.0*itime/3600 

!***********************************************************************************
! 2. Nested domains
!***********************************************************************************

! sort particles according to horizontal position and calculate index vector IPOINT

      do inest=1,numbnests
        delx = dxn(inest)
! ROIHU: 'goto 70' left the inest loop entirely; the comment says this nest.
! Same f77->f90 label-placement artefact as 50/60 below. (Behaviour only differs
! if dxn is not monotonically decreasing with nest index.)
        if (delx .le. 10000.0) cycle          ! for small grid size, no need to do convection 
        do ipart=1,numpart
          ipoint(ipart)=ipart
          igrid(ipart) = igridn(ipart,inest)
        enddo
        call sort2(numpart,igrid,ipoint)

!        print*,'step in nest'
! Now visit all grid columns where particles are present
! by going through the sorted particles

        igrold = -1
        do kpart=1,numpart
          igr = igrid(kpart)
          if (igr .eq. -1) cycle    ! ROIHU: was 'goto 60' -- see label-50 note
          ipart = ipoint(kpart)
!         sumall = sumall + 1
          if (igr .ne. igrold) then
! we are in a new grid column
            jy = (igr-1)/nxn(inest)
            ix = igr - jy*nxn(inest) - 1

! Interpolate all meteorological data needed for the convection scheme

! Interpolate all meteorological data needed for the convection scheme
 
          do kz=1,nuvz         ! nconvlev+1
! FLEXPART_WRF - used add_sfc_level for the shifting
! for W, it is not shifted, make sure w is 'true' vertical velocity!
 
            kzp = kz + add_sfc_level
           u1d(kz)=(un_wrf(ix,jy,kzp,mind1,inest)*dt2+ &
                    un_wrf(ix,jy,kzp,mind2,inest)*dt1)*dtt
           v1d(kz)=(vn_wrf(ix,jy,kzp,mind1,inest)*dt2+ &
                    vn_wrf(ix,jy,kzp,mind2,inest)*dt1)*dtt
           t1d(kz)=(tthn(ix,jy,kzp,mind1,inest)*dt2+ &
                    tthn(ix,jy,kzp,mind2,inest)*dt1)*dtt
           qv1d(kz)=(qvhn(ix,jy,kzp,mind1,inest)*dt2+ &
                     qvhn(ix,jy,kzp,mind2,inest)*dt1)*dtt
           p1d(kz)=(pphn(ix,jy,kzp,mind1,inest)*dt2+ &
                    pphn(ix,jy,kzp,mind2,inest)*dt1)*dtt
           dz1d(kz)=(zzhn(ix,jy,kzp+1,mind1,inest)*dt2+ &
                     zzhn(ix,jy,kzp+1,mind2,inest)*dt1)*dtt- &
                    (zzhn(ix,jy,kzp,mind1,inest)*dt2+ &
                     zzhn(ix,jy,kzp,mind2,inest)*dt1)*dtt
           w0avg1d(kz)=(wn_wrf(ix,jy,kz,mind1,inest)*dt2+ &
                        wn_wrf(ix,jy,kz,mind2,inest)*dt1)*dtt+ &
                       (wn_wrf(ix,jy,kz+1,mind1,inest)*dt2+ &
                        wn_wrf(ix,jy,kz+1,mind2,inest)*dt1)*dtt
           w0avg1d(kz)=0.5*w0avg1d(kz)
           rho1d(kz)=p1d(kz)/ &
                    (t1d(kz)*(1.0+0.608*qv1d(kz))) &
                     /287.0
 
          enddo 

!C Old convective mass fluxes
          do k=kts,kte
           umf(k)=umf3n(ix,jy,k,inest)
           uer(k)=uer3n(ix,jy,k,inest)
           udr(k)=udr3n(ix,jy,k,inest)
           dmf(k)=dmf3n(ix,jy,k,inest)
           der(k)=der3n(ix,jy,k,inest)
           ddr(k)=ddr3n(ix,jy,k,inest)
          enddo
           cu_top1=cu_topn(ix,jy,inest)
           cu_bot1=cu_botn(ix,jy,inest)



!alculate convection flux, updrought flux, entrainment, detrainment flux
!                            downdraft flux, entrainment ,detrainment flux
        warm_rain = .false.
        if (mp_physicsn(inest) .eq. 1 ) warm_rain = .true.

          if (if_update .eq. 1 ) then   !!! update
          CALL KF_ETA(nuvzmax,u1d,v1d,t1d,dz1d,qv1d,p1d,    &       ! IN
                rho1d,w0avg1d,cudt,delx,dt_conv,warm_rain,kts,kte,  &      ! IN
                  umf,uer,udr,dmf,der,ddr,cu_bot1,cu_top1)      ! OUT
          do k=kts,kte
           umf3n(ix,jy,k,inest)=umf(k)
           uer3n(ix,jy,k,inest)=uer(k)
           udr3n(ix,jy,k,inest)=udr(k)
           dmf3n(ix,jy,k,inest)=dmf(k)
           der3n(ix,jy,k,inest)=der(k)
           ddr3n(ix,jy,k,inest)=ddr(k)
          enddo
           cu_topn(ix,jy,inest)=cu_top1
           cu_botn(ix,jy,inest)=cu_bot1
          endif                       !!! update

 
           
           IF (cu_top1 .gt. cu_bot1) then     ! lconv
             
            lconv = .true. 
  
! Prepare data for redistributing particle

       CALL pre_redist_kf(nuvzmax,nuvz,umf,dmf,dz1d,p1d,delx,delt, & !  IN
            cu_bot1,cu_top1,      &                  ! IN
            zf,zh, &   ! OUT
            umfzf,dmfzf,fmix)                             ! OUT

           else
            lconv = .false.           
           ENDIF                              ! lconv


            igrold = igr
            ktop = 0
          endif
        
! treat particle only if column has convection
        if (lconv .eqv. .true.) then
! assign new vertical position to particle
 
!          ztold=ztra1(ipart)
          zp=ztra1(ipart)
 
       CALL redist_kf(lconvection,ldirect,delt,delx,  &         ! IN
                          dz1d,nzmax, nz,umf,uer,udr,dmf, &  ! IN
                            der,ddr,rho1d,          &        ! IN
                            zf,zh,                  &        ! IN
!                           umfzf,dmfzf,            &        ! IN
                            umfzf,dmfzf,fmix,       &        ! IN
                            zp)                              ! IN/OUT
         
          if (zp .lt. 0.0) zp=-1.0*zp
          if (zp .gt. height(nz)-0.5)  &
              zp = height(nz)-0.5 
          ztra1(ipart) = zp

! Calculate the gross fluxes across layer interfaces
!***************************************************

            if (iflux.eq.1) then
              itage=abs(itra1(ipart)-itramem(ipart))
              do  nage=1,nageclass
                if (itage.lt.lage(nage)) goto 47
           enddo
 47           continue

              if (nage.le.nageclass) &
             call calcfluxes(nage,ipart,real(xtra1(ipart)), &
             real(ytra1(ipart)),ztold)
            endif

          endif !(lconv .eqv. .true.)

       enddo
        enddo       !inest - loop
!       print*,'end of convmix'
!--------------------------------------------------------------------------
!     write(*,*)'############################################'
!     write(*,*)'TIME=',
!    &  itime
!     write(*,*)'fraction of particles under convection',
!    &  sumconv/(sumall+0.001) 
!     write(*,*)'total number of particles',
!    &  sumall 
!     write(*,*)'number of particles under convection',
!    &  sumconv
!     write(*,*)'############################################'

      return
end subroutine convmix_kfeta
